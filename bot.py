import os, json, requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === Настройки из окружения ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не задан TELEGRAM_TOKEN")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise RuntimeError("Не задан SPREADSHEET_ID")

creds_json = os.getenv("GOOGLE_CREDS_JSON")
if not creds_json:
    raise RuntimeError("Не задан GOOGLE_CREDS_JSON")
creds_info = json.loads(creds_json)

creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets_service = build("sheets", "v4", credentials=creds)

# Получаем название первого листа
meta = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET = meta["sheets"][0]["properties"]["title"]

# === Flask & Telegram helper ===
app = Flask(__name__)
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send(chat_id, text):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")
    if not chat_id:
        return "ok", 200

    cmd = text.strip().lower()
    if cmd.startswith("/start"):
        send(chat_id, "👋 Бот запущен.")
    elif cmd.startswith("/test"):
        # Пример записи в ячейку A1
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{FIRST_SHEET}'!A1",
            valueInputOption="RAW",
            body={"values":[["✅ Connected"]]}
        ).execute()
        send(chat_id, f"✅ Написал в лист «{FIRST_SHEET}»!")
    else:
        send(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
