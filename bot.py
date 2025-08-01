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

    # 2) /test — проверка Google Sheets
    elif text.startswith("/test"):
        # записываем A1 первой вкладки
        meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        first_title = meta["sheets"][0]["properties"]["title"]
        range_name = f"'{first_title}'!A1"
        body = {"values": [["✅ Bot connected"]]}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body=body
        ).execute()
        send_message(chat_id, f"✅ Google Sheets обновлены на листе «{first_title}».")

    # 3) Создать RFQ <название проекта>
    elif text.lower().startswith("создать rfq"):
        project_name = text[len("создать rfq"):].strip()
        # прочитать метаданные, найти все RFQ-* листы
        meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        existing = [
            s["properties"]["title"]
            for s in meta["sheets"]
            if s["properties"]["title"].startswith("RFQ-")
        ]
        next_num = len(existing) + 1
        new_title = f"RFQ-{next_num}"

        # создаём новый лист
        batch = {"requests":[{"addSheet":{"properties":{"title":new_title}}}]}
        resp = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID, body=batch
        ).execute()
        sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

        # пишем заголовки
        headers = [["Поставщик","Цена USD","Условия","Комментарий"]]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{new_title}'!A1",
            valueInputOption="RAW",
            body={"values":headers}
        ).execute()

        # формируем ссылку и отвечаем
        link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sheet_id}"
        send_message(chat_id, f"✔ Лист {new_title} для «{project_name}» создан: {link}")

    # 4) всё остальное — эхо
    else:
        send_message(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
