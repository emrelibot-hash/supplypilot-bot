import os
import re
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)

# === Настройки через переменные окружения ===
SPREADSHEET_ID    = os.getenv("SPREADSHEET_ID")  # ID Google Sheet
CREDS_JSON        = os.getenv("GOOGLE_CREDS_JSON")  # содержимое JSON сервис-аккаунта
SCOPES            = ["https://www.googleapis.com/auth/spreadsheets"]

if not SPREADSHEET_ID or not CREDS_JSON:
    raise RuntimeError("Не заданы SPREADSHEET_ID или GOOGLE_CREDS_JSON")

# Создаём креды и сервис
creds = service_account.Credentials.from_service_account_info(
    CREDS_JSON if isinstance(CREDS_JSON, dict) else __import__("json").loads(CREDS_JSON),
    scopes=SCOPES
)
sheets = build("sheets", "v4", credentials=creds).spreadsheets()

# Триггер-фразы
TRIGGERS = [
    "создай таблицу",
    "создай",
    "сделай таблицу",
    "сделай",
    "сделай сравнительную таблицу",
]

def parse_request(text: str):
    """Возвращает (project_name, list_of_offers) или (None, None)"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    header = lines[0].lower()
    if not any(header.startswith(t) for t in TRIGGERS):
        return None, None

    # имя проекта — всё после слова «таблицу» или после самого триггера
    m = re.match(r"(?:создай|сделай)(?: таблицу)?\s+(.+)", lines[0], flags=re.I)
    project = m.group(1).strip() if m else "НовыйПроект"
    offers = []
    # каждая строка — "Поставщик Цена Инкотермс Порт"
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) < 4:
            continue
        supplier = parts[0]
        price    = parts[1]
        incoterm = parts[2]
        port     = " ".join(parts[3:])
        offers.append([supplier, price, incoterm, port])
    return project, offers

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    text = data.get("text", "")
    project, offers = parse_request(text)
    if project is None:
        # не триггер = эхо
        return jsonify({"text": f"Получено: {text}"}), 200

    # создаём лист
    sheet_title = project
    try:
        sheets.batchUpdate(spreadsheetId=SPREADSHEET_ID, body={
            "requests": [{
                "addSheet": {"properties": {"title": sheet_title}}
            }]
        }).execute()
    except Exception as e:
        return jsonify({"text": f"❗ Не удалось создать лист «{sheet_title}»: {e}"}), 200

    # готовим данные: заголовки + предложения
    values = [["Поставщик", "Цена", "Инкотермс", "Порт"]] + offers
    sheets.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_title}'!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

    return jsonify({"text": f"✅ Лист «{sheet_title}» создан и заполнен ({len(offers)} КП)."}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
