import os
import re
import requests
import openai
import pandas as pd
from zipfile import BadZipFile
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Конфигурация ключей и ID ---
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
GOOGLE_CREDS_PATH = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")
SPREADSHEET_ID    = "1GL0_wzT3OaFBPQk6opiDaSdel4uVzpr_lcTbJtBNlxk"
EXCHANGE_API_URL  = "https://api.exchangerate-api.com/v4/latest/USD"

openai.api_key = OPENAI_API_KEY

# --- Постоянные наборы слов для парсинга RFQ/BOQ ---
INCOTERMS       = {"EXW","FCA","FAS","FOB","CFR","CIF","CPT","CIP","DAT","DAP","DDP"}
UNITS           = {"kg","g","ton","t","unit","pcs","piece","m","m2","m3"}
CURRENCIES      = {"USD","EUR","AZN","RUB","GEL"}
CREATE_TRIGGERS = [
    "создай ",
    "сделай ",
    "создай таблицу ",
    "сделай сравнительную таблицу ",
    "добавь таблицу "
]

exchange_rates = {}

def get_usd_rate(cur: str) -> float:
    cur = cur.upper()
    if cur == "USD":
        return 1.0
    global exchange_rates
    if not exchange_rates:
        exchange_rates.update(requests.get(EXCHANGE_API_URL).json().get("rates", {}))
    return exchange_rates.get(cur, 1.0)

def translate_via_gpt(text: str) -> str:
    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful translation assistant."},
            {"role": "user",   "content": f"Please translate to English, preserving technical terms and units:\n\n{text}"}
        ],
        temperature=0
    )
    return resp.choices[0].message.content.strip()

# Инициализация Google Sheets API
creds  = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets = build("sheets", "v4", credentials=creds)

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data    = request.get_json(force=True)
    msg     = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text    = (msg.get("text") or "").strip()
    lower   = text.lower()

    if not chat_id:
        return "ok", 200

    # --- 1) Авто-BOQ по прикреплённому Excel-файлу (xls/xlsx) без текста ---
    if msg.get("document") and not text:
        fn   = msg["document"].get("file_name", "").lower()
        mime = msg["document"].get("mime_type", "")
        if fn.endswith((".xlsx", ".xls")) and mime in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel"
        ):
            project = os.path.splitext(fn)[0]

            # Создаём новую вкладку BOQ-#
            meta     = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
            existing = [s["properties"]["title"] for s in meta["sheets"]
                        if s["properties"]["title"].startswith("BOQ-")]
            idx    = len(existing) + 1
            title  = f"BOQ-{idx}"
            resp   = sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":title}}}]}
            ).execute()
            sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
            link     = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sheet_id}"

            # Скачиваем файл из Telegram
            file_id = msg["document"]["file_id"]
            r       = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
            ).json()
            path    = r["result"]["file_path"]
            dl      = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{path}")
            with open("/tmp/tmp.xlsx", "wb") as f:
                f.write(dl.content)

            # Выбираем движок по расширению и читаем через pandas
            engine = "xlrd" if fn.endswith(".xls") else "openpyxl"
            try:
                df = pd.read_excel(
                    "/tmp/tmp.xlsx",
                    header=None,
                    dtype=str,
                    engine=engine
                )
            except BadZipFile:
                send_message(chat_id, "⚠ Файл не является корректным Excel-архивом. Авто-BOQ отменён.")
                return "ok", 200
            except ImportError:
                send_message(
                    chat_id,
                    f"⚠ Движок чтения `{engine}` не установлен. Добавьте в requirements.txt `{engine}`"
                )
                return "ok", 200
            except Exception as e:
                send_message(chat_id, f"⚠ Ошибка чтения Excel: {e}")
                return "ok", 200

            table = df.fillna("").values.tolist()

            # Переводим каждую ячейку через GPT
            translated = []
            for row in table:
                tr_row = []
                for cell in row:
                    txt = (cell or "").strip()
                    tr_row.append(translate_via_gpt(txt) if txt else "")
                translated.append(tr_row)

            # Записываем результат в Google Sheets
            sheets.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{title}'!A1",
                valueInputOption="RAW",
                body={"values": translated}
            ).execute()

            send_message(
                chat_id,
                f"✔ Авто-BOQ: лист {title} для проекта «{project}» создан и переведён:\n{link}"
            )
            return "ok", 200

        # файл не Excel
        send_message(chat_id, "⚠ Прикреплён не Excel-файл, авто-BOQ не выполнен.")
        return "ok", 200

    # --- 2) Стандартные команды ---
    if lower.startswith("/start"):
        send_message(chat_id, "👋 Привет! Бот запущен и готов к работе.")
        return "ok", 200

    if lower.startswith("/test"):
        meta  = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        title = meta["sheets"][0]["properties"]["title"]
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{title}'!A1",
            valueInputOption="RAW",
            body={"values":[["✅ Bot connected"]]}
        ).execute()
        send_message(chat_id, f"✅ Лист «{title}» обновлён.")
        return "ok", 200

    # --- 3) Обработка текстовых триггеров «создай…» и т.д. ---
    for trig in CREATE_TRIGGERS:
        if lower.startswith(trig):
            # Здесь можно вставить вашу логику обработки RFQ/BOQ из текстового сообщения
            send_message(chat_id, "⚙ Команда создания таблицы распознана (готово к доработке).")
            return "ok", 200

    # --- 4) Фолбэк ---
    send_message(chat_id, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
