import os
import re
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

app = Flask(__name__)

# === Настройки через переменные окружения ===
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")      # ID Google Sheet
CREDS_JSON     = os.getenv("GOOGLE_CREDS_JSON")    # JSON сервис-аккаунта
SCOPES         = ["https://www.googleapis.com/auth/spreadsheets"]

if not SPREADSHEET_ID or not CREDS_JSON:
    raise RuntimeError("Не заданы SPREADSHEET_ID или GOOGLE_CREDS_JSON")

# Создаём креды и сервис
creds_info = json.loads(CREDS_JSON) if isinstance(CREDS_JSON, str) else CREDS_JSON
creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
sheets = build("sheets", "v4", credentials=creds).spreadsheets()

# Триггер-фразы (нижний регистр)
TRIGGERS = [
    "создай таблицу",
    "создай",
    "сделай таблицу",
    "сделай",
    "сделай сравнительную таблицу",
]

def parse_request(text: str):
    """
    Возвращает (project_name, offers) или (None, None)
    offers = [ [supplier, price, incoterm, port], ... ]
    """
    # разбиваем на непустые строки
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None, None

    header = lines[0].lower()
    if not any(header.startswith(t) for t in TRIGGERS):
        return None, None

    # вытаскиваем имя проекта: всё после ключевого слова
    m = re.match(r"(?:создай|сделай)(?: таблицу)?\s+(.+)", lines[0], flags=re.I)
    project = m.group(1).strip() if m else "НовыйПроект"

    offers = []
    for ln in lines[1:]:
        # ожидаем минимум 4 колонки
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
    text = data.get("text", "").strip()

    project, offers = parse_request(text)
    if project is None:
        # не попали под триггер — просто эхом возвращаем
        return jsonify({"text": f"Получено: {text}"}), 200

    # пытаемся добавить новый лист
    try:
        sheets.batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests":[{"addSheet":{"properties":{"title": project}}}]}
        ).execute()
    except Exception as e:
        return jsonify({"text": f"❗ Не удалось создать лист «{project}»: {e}"}), 200

    # формируем данные и заливаем
    values = [["Поставщик","Цена","Инкотермс","Порт"]] + offers
    sheets.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{project}'!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

    return jsonify({"text": f"✅ Лист «{project}» создан и заполнен ({len(offers)} строк)."}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
