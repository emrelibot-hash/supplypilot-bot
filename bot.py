import os
import json
import requests
import tempfile

from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd

# ————— Настройки —————

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "ВАШ_SPREADSHEET_ID")
# Сервисный аккаунт: можно передать JSON в переменной GOOGLE_CREDS_JSON
creds_info = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets = build("sheets", "v4", credentials=creds)

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    """Универсальная отсылка сообщения в Telegram."""
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

def download_file(file_id: str) -> str:
    """Скачивает документ из Telegram, возвращает локальный путь."""
    # получаем путь к файлу
    r = requests.get(f"{API_URL}/getFile?file_id={file_id}")
    file_path = r.json()["result"]["file_path"]
    # скачиваем
    url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    resp = requests.get(url, stream=True)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    with open(tmp.name, "wb") as f:
        for chunk in resp.iter_content(1024):
            f.write(chunk)
    return tmp.name

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg  = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return "ok", 200

    text = msg.get("text", "")
    # Обработка стартовой команды
    if text.startswith("/start"):
        send_message(chat_id, "👋 Привет! Пришлите BOQ-файл, и я создам для вас лист в Google Sheets.")
        return "ok", 200

    # Если пользователь прислал документ
    if "document" in msg:
        file_id = msg["document"]["file_id"]
        send_message(chat_id, "📥 Скачиваю файл и обрабатываю…")
        try:
            local_path = download_file(file_id)
            # Читаем в DataFrame без перевода
            df = pd.read_excel(local_path, header=None, dtype=str, engine="openpyxl")
        except Exception as e:
            send_message(chat_id, f"⚠ Ошибка при чтении файла: {e}")
            return "ok", 200

        # Узнаём список существующих листов, чтобы назначить уникальное имя
        meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        existing = {sh["properties"]["title"] for sh in meta["sheets"]}
        # Новое имя «BOQ-<N>»
        idx = 1
        while f"BOQ-{idx}" in existing:
            idx += 1
        new_title = f"BOQ-{idx}"

        # Создаём лист
        try:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={
                    "requests": [
                        {"addSheet": {"properties": {"title": new_title}}}
                    ]
                }
            ).execute()
        except Exception as e:
            send_message(chat_id, f"⚠ Не удалось создать лист: {e}")
            return "ok", 200

        # Подготавливаем values и заливаем
        values = df.fillna("").values.tolist()
        try:
            sheets.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{new_title}'!A1",
                valueInputOption="RAW",
                body={"values": values}
            ).execute()
        except Exception as e:
            send_message(chat_id, f"⚠ Не удалось записать данные: {e}")
            return "ok", 200

        send_message(chat_id, f"✅ Лист «{new_title}» создан и заполнен данными.")
        return "ok", 200

    # Во всех остальных случаях — эхо
    send_message(chat_id, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    # на Render.com PORT задаётся окружением
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
