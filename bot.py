import os
import re
import datetime
import requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ——————————————————————————————————————————————————————
# 1) Настройки из окружения
# ——————————————————————————————————————————————————————
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не задано окружение TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise RuntimeError("Не задано окружение SPREADSHEET_ID")

CREDS_PATH = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")
if not os.path.isfile(CREDS_PATH):
    raise RuntimeError(f"Не найден файл учётных данных: {CREDS_PATH}")

# ——————————————————————————————————————————————————————
# 2) Инициализация Google Sheets API
# ——————————————————————————————————————————————————————
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = service_account.Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
sheets_service = build("sheets", "v4", credentials=creds)

# ——————————————————————————————————————————————————————
# 3) Flask
# ——————————————————————————————————————————————————————
app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

# парсер строки вида: "Name 15 USD/pcs FCA Moscow"
LINE_RE = re.compile(r"^(\S+)\s+([\d\.]+)\s+([A-Z]{3}/\w+)\s+(\w+)\s+(.+)$")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg  = data.get("message", {})
    chat = msg.get("chat", {})
    text = msg.get("text", "")
    chat_id = chat.get("id")

    if not chat_id:
        return "ok", 200

    # — /start
    if text.startswith("/start"):
        send_message(chat_id, "Бот запущен ✅ Отправьте «Создай таблицу <имя проекта>» + BOQ в одном сообщении.")
        return "ok", 200

    # — команды создания
    trigger = text.lower().strip().split()[0]
    if trigger in ("создай", "сделай", "создай таблицу", "сделай сравнительную таблицу"):
        # ищем наименование проекта в первой строке
        first_line = text.splitlines()[0]
        # убираем слово «создай» и всё лишнее
        proj_name = re.sub(r"(?i)^(создай|сделай)( таблицу| сравнительную таблицу)?\s*", "", first_line).strip()
        if not proj_name:
            proj_name = datetime.datetime.now().strftime("BOQ-%Y%m%d_%H%M%S")
        sheet_title = f"BOQ-{proj_name}"

        # создаём новый лист
        try:
            sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":sheet_title}}}]}
            ).execute()
        except Exception as e:
            send_message(chat_id, f"❌ Не удалось создать лист «{sheet_title}»: {e}")
            return "ok", 200

        # заполним заголовки
        headers = [["Supplier", "Price", "Unit", "Incoterm", "Place"]]
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{sheet_title}'!A1:E1",
            valueInputOption="RAW",
            body={"values": headers}
        ).execute()

        # теперь парсим все последующие строки
        lines = text.splitlines()[1:]
        rows = []
        for ln in lines:
            m = LINE_RE.match(ln.strip())
            if m:
                rows.append(m.groups())
        if rows:
            sheets_service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{sheet_title}'!A2",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows}
            ).execute()
            send_message(chat_id, f"✅ Лист «{sheet_title}» создан и заполнен {len(rows)} строками.")
        else:
            send_message(chat_id, f"⚠ Лист «{sheet_title}» создан, но не найдено ни одной строки BOQ для добавления.")
        return "ok", 200

    # — всё остальное — эхо
    send_message(chat_id, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    # для локальной отладки:
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
