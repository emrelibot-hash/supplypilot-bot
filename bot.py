import os
import json
import requests
from flask import Flask, request, abort
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ——— Настройки ———

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не задана переменная окружения TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Google Sheets
SPREADSHEET_ID = "1zKd3hq7R-CI_i0azdZsdIPihBNT-6BlhADW0M0eiGpo"

# Путь к JSON файлу сервис-аккаунта
# Убедитесь, что вы загрузили vika-bot.json в корень репозитория
CREDS_PATH = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")
if not os.path.exists(CREDS_PATH):
    raise RuntimeError(f"Не найден файл учётных данных: {CREDS_PATH}")

# Загружаем ключи и создаём клиента Google Sheets API
creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets_service = build("sheets", "v4", credentials=creds)

# Получаем название первого листа (если нужно)
meta = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET = meta["sheets"][0]["properties"]["title"]

# ——— Flask приложение ———

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    }).raise_for_status()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg = data.get("message")
    if not msg:
        return "ok", 200

    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    if text.lower().startswith("/start"):
        send_message(chat_id, "👋 Бот запущен и готов к работе.")
    elif text.lower().startswith("/test"):
        # Проверка обновления A1
        range_name = f"'{FIRST_SHEET}'!A1"
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption="RAW",
            body={"values":[["✅ Bot connected"]]}
        ).execute()
        send_message(chat_id, f"✅ Лист «{FIRST_SHEET}» обновлён.")
    else:
        # Эхо-режим
        send_message(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    # Port по умолчанию Render — 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
