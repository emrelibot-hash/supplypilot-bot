import os
import re
import requests
import openai
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Конфигурирование API-ключей ---
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
GOOGLE_CREDS_PATH= os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")
SPREADSHEET_ID   = "1GL0_wzT3OaFBPQk6opiDaSdel4uVzpr_lcTbJtBNlxk"
EXCHANGE_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"

openai.api_key = OPENAI_API_KEY

# --- Постоянные множества для RFQ ---
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

# Кэш курсов валют
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
    """Переводит любой текст на английский через GPT."""
    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful translation assistant."},
            {"role": "user",   "content": f"Please translate the following text into English, preserving any technical terms and units: «{text}»"}
        ],
        temperature=0
    )
    return resp.choices[0].message.content.strip()

# --- Инициализация Google Sheets API ---
creds   = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets  = build("sheets", "v4", credentials=creds)

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                  json={"chat_id": chat_id, "text": text})

@app.route("/webhook", methods=["POST"])
def webhook():
    data    = request.get_json(force=True)
    msg     = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text    = (msg.get("text") or "").strip()
    lower   = text.lower()

    if not chat_id:
        return "ok", 200

    # /start
    if lower.startswith("/start"):
        send_message(chat_id, "👋 Привет! Бот готов к работе.")
        return "ok", 200

    # /test
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

    # Главный блок: «создай…» + сразу BOQ или RFQ
    for trig in CREATE_TRIGGERS:
        if lower.startswith(trig):
            lines     = text.splitlines()
            project   = lines[0][len(trig):].strip() or "Без имени"
            data_lines= [l for l in lines[1:] if l.strip()]
            is_boq    = any(';' in l or '\t' in l for l in data_lines)
            prefix    = "BOQ-" if is_boq else "RFQ-"

            # создаём новую вкладку
            meta     = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
            existing = [s["properties"]["title"] for s in meta["sheets"]
                        if s["properties"]["title"].startswith(prefix)]
            idx   = len(existing) + 1
            title = f"{prefix}{idx}"
            resp  = sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":title}}}]}
            ).execute()
            sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
            link     = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sheet_id}"

            if is_boq:
                # --- BOQ: парсим CSV- или таб-формат, переводим через GPT, записываем ---
                table = [re.split(r'[;\t]+', row) for row in data_lines]
                translated = []
                for row in table:
                    tr_row = []
                    for cell in row:
                        txt = cell.strip()
                        tr_row.append(translate_via_gpt(txt) if txt else "")
                    translated.append(tr_row)
                sheets.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{title}'!A1",
                    valueInputOption="RAW",
                    body={"values": translated}
                ).execute()
                send_message(chat_id, f"✔ Лист {title} для BOQ «{project}» создан и переведён: {link}")
                return "ok", 200

            else:
                # --- RFQ: базовая шапка + парсинг КП ---
                sheets.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{title}'!A1",
                    valueInputOption="RAW",
                    body={"values":[["Поставщик","Цена","Ед.изм.","Incoterm","Условия","Комментарий"]]}
                ).execute()

                rows, usd_vals, seen = [], [], set()
                pat = re.compile(
                    rf'(?P<price>[\d\.,]+)\s*(?P<currency>{"|".join(CURRENCIES)})?'
                    rf'(?:\/\s*(?P<unit>{"|".join(UNITS)}))?',
                    flags=re.IGNORECASE
                )
                for ln in data_lines:
                    m = pat.search(ln)
                    if not m: continue
                    s,e = m.span()
                    sup = ln[:s].strip("—-: ").title()
                    if sup.lower() in seen: continue
                    seen.add(sup.lower())

                    num = m.group("price").replace(",",".")
                    cur = (m.group("currency") or "USD").upper()
                    unit= (m.group("unit") or "").lower()
                    rate= get_usd_rate(cur)
                    usd = float(num)/rate
                    usd_vals.append(usd)

                    tail = ln[e:].strip("—-: ").split()
                    inc  = next((p.upper() for p in tail if p.upper() in INCOTERMS), "")
                    if inc in tail: tail.remove(inc)
                    cond = " ".join(tail)

                    rows.append([sup, f"{num} {cur}", unit, inc, cond, ""])

                if rows:
                    sheets.spreadsheets().values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"'{title}'!A2",
                        valueInputOption="RAW",
                        insertDataOption="INSERT_ROWS",
                        body={"values": rows}
                    ).execute()
                    best = usd_vals.index(min(usd_vals))
                    # сброс цвета и подсветка лучшего
                    reqs = [
                        {"repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 1,
                                "endRowIndex": 1+len(rows),
                                "startColumnIndex": 0,
                                "endColumnIndex": 6
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": None}},
                            "fields": "userEnteredFormat.backgroundColor"
                        }},
                        {"repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 1+best,
                                "endRowIndex": 2+best,
                                "startColumnIndex": 0,
                                "endColumnIndex": 6
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor":
                                {"red":0.8, "green":1.0, "blue":0.8}}},
                            "fields": "userEnteredFormat.backgroundColor"
                        }}
                    ]
                    sheets.spreadsheets().batchUpdate(
                        spreadsheetId=SPREADSHEET_ID, body={"requests": reqs}
                    ).execute()
                    send_message(chat_id,
                        f"✔ Лист {title} для «{project}» создан: {link}\n"
                        f"➡ Добавлено {len(rows)} строк, лучший вариант (строка {best+2}) подсвечен.")
                    return "ok", 200

                send_message(chat_id, f"✔ Лист {title} для «{project}» создан: {link}")
                return "ok", 200

    # В остальных случаях — просто эхо
    send_message(chat_id, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
