import os
import requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === Настройки из окружения ===
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
API_URL          = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID", "16KY51jQAXWc9j2maNw_XwA2uIcCX5ApIZblDahYQJcU")
GOOGLE_CREDS_PATH= os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")

# === Инициализация Google Sheets API ===
creds = service_account.Credentials.from_service_account_file(
    GOOGLE_CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets_service = build("sheets", "v4", credentials=creds)

# Узнаём название первого листа, чтобы обращаться динамически
meta = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET_TITLE = meta["sheets"][0]["properties"]["title"]

# === Flask-приложение ===
app = Flask(__name__)

def send_message(chat_id: int, text: str):
    """Отправить сообщение в Telegram."""
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg  = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text    = msg.get("text", "")

    if not chat_id:
        return "ok", 200

    # 👇 Обработка команд
    if text.startswith("/start"):
        send_message(chat_id, "👋 Привет! Бот запущен и готов к работе.")
    elif text.startswith("/test"):
        # Пишем в ячейку A1 первого листа
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
        # Эхо
        send_message(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    # Порт берётся из $PORT (Render) или 5000 локально
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
