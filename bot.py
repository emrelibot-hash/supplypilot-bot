import os
import json
import requests
import pandas as pd
import openai

from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === Настройки Telegram ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не задана переменная TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# === Настройки Google Sheets ===
SPREADSHEET_ID = "16KY51jQAXWc9j2maNw_XwA2uIcCX5ApIZblDahYQJcU"

# Загружаем креденшелы сервисного аккаунта
creds = None
if os.getenv("GOOGLE_CREDS_JSON"):
    try:
        creds_info = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
        creds = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    except json.JSONDecodeError:
        raise RuntimeError("GOOGLE_CREDS_JSON не является корректным JSON")
else:
    # fallback на файл
    creds_path = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")
    if not os.path.exists(creds_path):
        raise RuntimeError("Не найден файл сервисного аккаунта, "
                           "укажите GOOGLE_CREDS_JSON или файл по GOOGLE_CREDS_PATH")
    creds = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

sheets = build("sheets", "v4", credentials=creds)
meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET = meta["sheets"][0]["properties"]["title"]

# === Настройки OpenAI ===
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise RuntimeError("Не задан OPENAI_API_KEY")

# === Flask ===
app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

def translate_text(text: str, target_lang="EN") -> str:
    prompt = (
        f"Please translate the following text to {target_lang}, preserving "
        "technical terms and units. Return the result in plain text:\n\n"
        + text
    )
    resp = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content.strip()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg  = data.get("message", {})
    cid  = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not cid:
        return "ok", 200

    # Тестовая команда
    if text.startswith("/test"):
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{FIRST_SHEET}'!A1",
            valueInputOption="RAW",
            body={"values": [["✅ Bot connected"]]}
        ).execute()
        send_message(cid, f"✅ Google Sheets обновлены на листе «{FIRST_SHEET}».")
        return "ok", 200

    # Команда создания таблицы с BOQ
    low = text.lower()
    if low.startswith(("создай таблицу", "сделай таблицу", "создай ", "сделай ")):
        # Разбиваем: первая строка — команда, остальное — BOQ
        lines = text.splitlines()
        header = lines[0]
        boq_raw = "\n".join(lines[1:]).strip()
        if not boq_raw:
            send_message(cid, "❗ После заголовка таблицы нужно прислать BOQ на следующих строках.")
            return "ok", 200

        # Извлекаем имя проекта
        name = header.strip().split(maxsplit=2)[-1]
        sheet_title = f"BOQ-{name}"

        # Переводим BOQ на английский
        try:
            boq_en = translate_text(boq_raw)
        except Exception as e:
            send_message(cid, f"❗ Ошибка перевода: {e}")
            return "ok", 200

        # Пытаемся создать лист; если он уже есть — используем его
        try:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":sheet_title}}}]}
            ).execute()
            send_message(cid, f"✅ Лист «{sheet_title}» создан.")
        except HttpError as e:
            if "already exists" in e.content.decode():
                send_message(cid, f"ℹ Лист «{sheet_title}» уже существует — заполняю его.")
            else:
                send_message(cid, f"❗ Не удалось создать лист: {e}")
                return "ok", 200

        # Парсим en-BOQ в табличку
        try:
            rows = [row.split() for row in boq_en.splitlines() if row.strip()]
            df = pd.DataFrame(rows, columns=["Item","Qty","UnitPrice","Incoterm","Location"])
        except Exception as e:
            send_message(cid, f"❗ Ошибка парсинга BOQ: {e}")
            return "ok", 200

        # Записываем в Google Sheets
        try:
            sheets.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{sheet_title}'!A1",
                valueInputOption="RAW",
                body={"values":[df.columns.tolist()] + df.values.tolist()}
            ).execute()
            send_message(cid, f"✅ Лист «{sheet_title}» заполнен.")
        except Exception as e:
            send_message(cid, f"❗ Ошибка записи в таблицу: {e}")

        return "ok", 200

    # Всё остальное — эхом
    send_message(cid, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
