import os
import re
import requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === Настройки из окружения ===
TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
SPREADSHEET_ID     = os.environ["SPREADSHEET_ID"]
CREDS_PATH         = os.environ.get("GOOGLE_CREDS_PATH", "vika-bot.json")
API_URL            = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# === Google Sheets API ===
if not os.path.exists(CREDS_PATH):
    raise RuntimeError(f"Не найден файл учётных данных: {CREDS_PATH!r}")

creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets = build("sheets", "v4", credentials=creds)

# Получим название первой вкладки для /test
meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET = meta["sheets"][0]["properties"]["title"]

# === Flask & Telegram ===
app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg  = data.get("message", {})
    chat = msg.get("chat", {})
    text = msg.get("text", "").strip()
    chat_id = chat.get("id")

    if not chat_id:
        return "ok", 200

    lower = text.lower()
    # /start
    if lower.startswith("/start"):
        send_message(chat_id, "👋 Привет! Я готов работать.")
        return "ok", 200

    # /test
    if lower.startswith("/test"):
        try:
            sheets.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{FIRST_SHEET}'!A1",
                valueInputOption="RAW",
                body={"values":[["✅ Bot connected"]]}
            ).execute()
            send_message(chat_id, f"✅ Ячейка A1 листа «{FIRST_SHEET}» обновлена.")
        except HttpError as e:
            send_message(chat_id, "Ошибка при обновлении: " + str(e))
        return "ok", 200

    # Обработать «Создай таблицу …» и BOQ
    trigger = None
    for kw in ["создай таблицу", "сделай таблицу", "создай", "сделай сравнительную таблицу"]:
        if lower.startswith(kw):
            trigger = kw
            break

    if trigger:
        # Первый ряд: «Создай таблицу Название»
        header, *lines = text.splitlines()
        # вырезаем команду
        proj_name = header[len(trigger):].strip(" «»:–-")
        if not proj_name:
            send_message(chat_id, "❗ Не указано имя таблицы после команды.")
            return "ok", 200

        # 1) Создать лист, если не существует
        try:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":proj_name}}}]}
            ).execute()
        except HttpError as e:
            # если уже есть — игнорируем
            if "already exists" not in e.error_details[0]:
                send_message(chat_id, f"Ошибка при создании листа: {e}")
                return "ok", 200

        # 2) Пробиваем заголовок
        header_row = [["№", "Поставщик", "Цена", "Инкотермс", "Локация"]]
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{proj_name}'!A1:E1",
            valueInputOption="RAW",
            body={"values": header_row}
        ).execute()

        # 3) Парсим каждую строку BOQ
        values = []
        pattern = re.compile(r"^(.+?)\s+([\d.,]+\s*\w+/\w+)\s+(\w+)\s+(.+)$")
        for idx, line in enumerate(lines, start=1):
            m = pattern.match(line.strip())
            if not m:
                continue
            supplier, price, inc, loc = m.groups()
            values.append([idx, supplier, price, inc, loc])

        # 4) Дозаписываем данные
        if values:
            sheets.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{proj_name}'!A2",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": values}
            ).execute()
            send_message(chat_id, f"✅ Таблица «{proj_name}» заполнена ({len(values)} строк).")
        else:
            send_message(chat_id, "⚠ Не удалось распарсить ни одной строки BOQ.")
        return "ok", 200

    # Всё остальное — эхо
    send_message(chat_id, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    # порт указывает Render автоматически через $PORT, локально — 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
