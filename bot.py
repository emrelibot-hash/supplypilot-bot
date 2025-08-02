import os
import json
import requests
from flask import Flask, request, abort
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ------------ Настройки из окружения ------------

# Telegram
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не задан TELEGRAM_TOKEN в переменных окружения")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Google Sheets
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise RuntimeError("Не задан SPREADSHEET_ID в переменных окружения")

# Сервисный аккаунт Google — полный JSON в переменной GOOGLE_CREDS_JSON
creds_json = os.environ.get("GOOGLE_CREDS_JSON")
if not creds_json:
    raise RuntimeError("Не задан GOOGLE_CREDS_JSON в переменных окружения")
creds_dict = json.loads(creds_json)

# Создаём учётку и сервис
creds = service_account.Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets_service = build("sheets", "v4", credentials=creds)

# Получим название первого листа для теста
meta = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET_TITLE = meta["sheets"][0]["properties"]["title"]

# ------------ Flask & Helpers ------------

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    """Отправить текстовое сообщение в Telegram."""
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    if "message" not in data:
        return "ok", 200

    msg = data["message"]
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")
    if not chat_id:
        return "ok", 200

    # Обработка команд
    lower = text.strip().lower()
    if lower.startswith("/start"):
        send_message(chat_id, "👋 Привет! Бот запущен и готов к работе.")
    elif lower.startswith("/test"):
        # Пишем в A1 на первом листе
        range_name = f"'{FIRST_SHEET_TITLE}'!A1"
        body = {"values": [["✅ Bot connected"]]}
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body=body
        ).execute()
        send_message(chat_id, f"✅ Google Sheets обновлены на листе «{FIRST_SHEET_TITLE}».")
    else:
        # По умолчанию — эхо
        send_message(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
