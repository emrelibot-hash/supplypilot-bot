import os
import json
import tempfile
import requests
import openai
import pandas as pd
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === Настройки Telegram ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# === Настройки Google Sheets ===
SPREADSHEET_ID = "16KY51jQAXWc9j2maNw_XwA2uIcCX5ApIZblDahYQJcU"
creds_info = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets = build("sheets", "v4", credentials=creds)
meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
FIRST_SHEET = meta["sheets"][0]["properties"]["title"]

# === Настройки OpenAI ===
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })

def translate_text(text: str, target_lang="EN") -> str:
    """
    Переводит произвольный текст через ChatGPT
    """
    prompt = (
        f"Please translate the following text to {target_lang}, preserving "
        "technical terms:\n\n" + text
    )
    # Новый интерфейс OpenAI Python SDK >=1.0.0:
    resp = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    msg  = data.get("message", {})
    cid  = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not cid:
        return "ok", 200

    # Тестовый простой кейс
    if text.startswith("/test"):
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{FIRST_SHEET}'!A1",
            valueInputOption="RAW",
            body={"values": [["✅ Bot connected"]]}
        ).execute()
        send_message(cid, f"✅ Google Sheets на листе «{FIRST_SHEET}» обновлены.")
        return "ok", 200

    # Обработка команды создания таблицы + BOQ
    if text.lower().startswith(("создай таблицу", "сделай таблицу", "создай", "сделай")):
        # Выделяем имя проекта и BOQ из текста
        # Формат: "Создай таблицу <Имя>\n<BOQ в произвольной форме>"
        try:
            header, boq_raw = text.split("\n", 1)
            name = header.strip().split(maxsplit=2)[-1]
        except ValueError:
            send_message(cid, "❗ Формат: Создай таблицу <Имя проекта>, затем на новой строке BOQ.")
            return "ok", 200

        # Переводим BOQ на английский
        boq_en = translate_text(boq_raw)

        # Создаём новый лист
        new_title = f"BOQ-{name}"
        try:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":new_title}}}]}
            ).execute()
        except Exception as e:
            send_message(cid, f"❗ Не удалось создать лист «{new_title}»: {e}")
            return "ok", 200

        # Парсим BOQ в DataFrame
        df = (
            pd.DataFrame(
                [row.split() for row in boq_en.splitlines()],
                columns=["Item", "Qty", "UnitPrice", "Incoterm", "Location"]
            )
        )

        # Записываем в таблицу
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{new_title}'!A1",
            valueInputOption="RAW",
            body={"values":[df.columns.tolist()] + df.values.tolist()}
        ).execute()

        send_message(cid, f"✅ Лист «{new_title}» создан и заполнен.")
        return "ok", 200

    # Всё остальное — эхом
    send_message(cid, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
