import os
import json
import requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Настройки ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

SPREADSHEET_ID = "1GL0_wzT3OaFBPQk6opiDaSdel4uVzpr_lcTbJtBNlxk"
CREDS_PATH = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")

# Инициализируем Google Sheets API
creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
service = build("sheets", "v4", credentials=creds)

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data    = request.get_json(force=True)
    msg     = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text    = msg.get("text", "")

    if not chat_id:
        return "ok", 200

    # 1) /start
    if text.startswith("/start"):
        send_message(chat_id, "👋 Привет, Низами! Бот запущен и готов к работе.")

    # 2) /test
    elif text.startswith("/test"):
        meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        first_title = meta["sheets"][0]["properties"]["title"]
        range_name = f"'{first_title}'!A1"
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body={"values":[["✅ Bot connected"]]}
        ).execute()
        send_message(chat_id, f"✅ Google Sheets обновлены на листе «{first_title}».")

    # 3) Создать RFQ
    elif text.lower().startswith("создать rfq"):
        project_name = text[len("создать rfq"):].strip()
        meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        existing = [
            s["properties"]["title"]
            for s in meta["sheets"]
            if s["properties"]["title"].startswith("RFQ-")
        ]
        next_num = len(existing) + 1
        new_title = f"RFQ-{next_num}"
        batch = {"requests":[{"addSheet":{"properties":{"title":new_title}}}]}
        resp = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID, body=batch
        ).execute()
        sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
        headers = [["Поставщик","Цена USD","Условия","Комментарий"]]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{new_title}'!A1",
            valueInputOption="RAW",
            body={"values":headers}
        ).execute()
        link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sheet_id}"
        send_message(chat_id, f"✔ Лист {new_title} для «{project_name}» создан: {link}")

    # 4) Добавь КП к RFQ-…
    elif text.lower().startswith("добавь кп к rfq-"):
        # разбиваем заголовок и данные
        head, _, body = text.partition(":")
        rfq_label = head.strip().split()[-1].upper()         # e.g. "RFQ-1"
        lines = [l.strip() for l in body.strip().splitlines() if l.strip()]
        rows = []
        for line in lines:
            # разделяем по EM dash или обычному тире
            if "—" in line:
                sup, rest = line.split("—",1)
            elif "-" in line:
                sup, rest = line.split("-",1)
            else:
                continue
            sup = sup.strip()
            parts = rest.strip().split()  # e.g. ["$10.5/kg","FCA","Ordu"]
            price = parts[0]
            terms = " ".join(parts[1:]) if len(parts)>1 else ""
            rows.append([sup, price, terms, ""])
        # вставляем после заголовка
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{rfq_label}'!A2",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values":rows}
        ).execute()
        send_message(chat_id, f"➡ Добавлено {len(rows)} строк(и) в таблицу {rfq_label}.")

    # 5) всё остальное
    else:
        send_message(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
