import os
import json
import requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Google Sheets
SPREADSHEET_ID = "1GL0_wzT3OaFBPQk6opiDaSdel4uVzpr_lcTbJtBNlxk"
# Считываем файл сервисного аккаунта
CREDS_PATH = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")
creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
service = build("sheets", "v4", credentials=creds)

# Получаем метаданные, чтобы узнать реальное имя первой вкладки
meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET_TITLE = meta["sheets"][0]["properties"]["title"]

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not chat_id:
        return "ok", 200

    if text.startswith("/start"):
        send_message(chat_id, "👋 Привет, Низами! Бот запущен и готов к работе.")
    elif text.startswith("/test"):
        # Динамический диапазон
        range_name = f"'{FIRST_SHEET_TITLE}'!A1"
        body = {"values": [["✅ Bot connected"]]}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body=body
        ).execute()
        send_message(chat_id, f"✅ Google Sheets обновлены на листе «{FIRST_SHEET_TITLE}».")
    else:
        send_message(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
