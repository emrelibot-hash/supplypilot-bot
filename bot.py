import os
import json
from flask import Flask, request, jsonify, abort
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

app = Flask(__name__)

# --- Настройка через переменные окружения ---
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

if not SPREADSHEET_ID:
    raise RuntimeError("Не задано SPREADSHEET_ID в переменных окружения")

if not GOOGLE_CREDS_JSON:
    raise RuntimeError("Не задано GOOGLE_CREDS_JSON в переменных окружения")

# Парсим JSON-строку с учётными данными сервис-аккаунта
creds_info = json.loads(GOOGLE_CREDS_JSON)
creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
sheets_service = build("sheets", "v4", credentials=creds)

# --- Вспомогательные функции ---
def parse_request(text: str):
    """
    Ожидаем текст вида:
      НазваниеПроекта
      Item1 15 USD/pcs FCA Moscow
      Item2 20 EUR/pcs DAP Tbilisi
      ...
    """
    # убираем пустые строки и пробелы по краям
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Пустой запрос")

    project_name = lines[0]
    offers = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue  # пропускаем некорректные строки
        item, price, unit, incoterm, port = parts[:5]
        offers.append({
            "item": item,
            "price": price,
            "unit": unit,
            "incoterm": incoterm,
            "port": port
        })
    if not offers:
        raise ValueError("Нет корректных строк с предложениями")
    return project_name, offers

def create_or_clear_sheet(title: str):
    """Создаёт лист с данным названием или очищает, если уже есть."""
    try:
        # Попытка добавить новый лист
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [
                {"addSheet": {"properties": {"title": title}}}
            ]}
        ).execute()
    except HttpError as e:
        # если уже существует — просто очищаем его
        if e.resp.status == 400 and "already exists" in str(e):
            sheets_service.spreadsheets().values().clear(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{title}'"
            ).execute()
        else:
            raise

def fill_sheet(title: str, offers: list):
    """Заполняет лист: заголовок + данные."""
    values = [["Позиция", "Цена", "Единица", "Инкотермс", "Порт"]]
    for o in offers:
        values.append([o["item"], o["price"], o["unit"], o["incoterm"], o["port"]])
    sheets_service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{title}'!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

# --- Основной эндпоинт webhook ---
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "text" not in data:
        abort(400, "Нет поля text в запросе")
    text = data["text"]

    try:
        project, offers = parse_request(text)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        create_or_clear_sheet(project)
        fill_sheet(project, offers)
    except HttpError as e:
        return jsonify({"error": f"Google API error: {e}"}), 500

    return jsonify({
        "status": "ok",
        "message": f"Лист «{project}» создан и заполнен ({len(offers)} строк)."
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
