import os
import time
import json
import requests

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ——— Настройки ———
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")  # ваш токен бота
API_URL          = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
SPREADSHEET_ID   = "16KY51jQAXWc9j2maNw_XwA2uIcCX5ApIZblDahYQJcU"  # новый ID вашей таблицы
CREDS_PATH       = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")

# ——— Инициализация Google Sheets API ———
creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
sheets_service = build("sheets", "v4", credentials=creds)
# узнаём название первого листа
meta = sheets_service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET = meta["sheets"][0]["properties"]["title"]


def send_message(chat_id: int, text: str):
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )


def handle_update(message: dict):
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text.startswith("/start"):
        send_message(chat_id, "👋 Привет! Бот запущен и готов к работе.")
        return

    if text.startswith("/test"):
        # обновляем ячейку A1 на первом листе
        rng = f"'{FIRST_SHEET}'!A1"
        body = {"values": [["✅ Bot connected (polling)"]]}
        sheets_service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=rng,
            valueInputOption="RAW",
            body=body
        ).execute()
        send_message(chat_id, f"✅ Google Sheets обновлены на листе «{FIRST_SHEET}».")
        return

    # любой другой текст — просто эхо
    send_message(chat_id, f"Получено: {text}")


def get_updates(offset=None, timeout=60):
    params = {"timeout": timeout}
    if offset:
        params["offset"] = offset
    resp = requests.get(f"{API_URL}/getUpdates", params=params)
    result = resp.json()
    return result.get("result", [])


if __name__ == "__main__":
    print("Polling bot started…")
    last_update_id = None

    while True:
        try:
            updates = get_updates(offset=last_update_id, timeout=30)
            for upd in updates:
                last_update_id = upd["update_id"] + 1
                if "message" in upd:
                    handle_update(upd["message"])
        except Exception as e:
            # на ошибках ждем немного и повторяем
            print("Error in polling loop:", e)
            time.sleep(5)
