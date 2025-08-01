import os
import re
import requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Настройки ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL        = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
SPREADSHEET_ID = "1GL0_wzT3OaFBPQk6opiDaSdel4uVzpr_lcTbJtBNlxk"
CREDS_PATH     = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")

# Инициализация Sheets API
creds   = service_account.Credentials.from_service_account_file(
    CREDS_PATH,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
service = build("sheets", "v4", credentials=creds)

app = Flask(__name__)

def send_message(chat_id: int, text: str):
    requests.post(f"{API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

@app.route("/webhook", methods=["POST"])
def webhook():
    data    = request.get_json(force=True)
    msg     = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text    = msg.get("text", "")

    if not chat_id:
        return "ok", 200

    # 1) /start
    if text.startswith("/start"):
        send_message(chat_id, "👋 Привет, Низами! Бот запущен и готов к работе.")

    # 2) /test
    elif text.startswith("/test"):
        meta        = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        first_title = meta["sheets"][0]["properties"]["title"]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{first_title}'!A1",
            valueInputOption="RAW",
            body={"values":[["✅ Bot connected"]]}
        ).execute()
        send_message(chat_id, f"✅ Google Sheets обновлены на листе «{first_title}».")

    # 3) Создать RFQ
    elif text.lower().startswith("создать rfq"):
        project_name = text[len("создать rfq"):].strip()
        meta         = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        existing     = [
            s["properties"]["title"]
            for s in meta["sheets"]
            if s["properties"]["title"].startswith("RFQ-")
        ]
        next_num = len(existing) + 1
        new_title = f"RFQ-{next_num}"
        resp = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests":[{"addSheet":{"properties":{"title":new_title}}}]}
        ).execute()
        sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{new_title}'!A1",
            valueInputOption="RAW",
            body={"values":[["Поставщик","Цена USD","Условия","Комментарий"]]}
        ).execute()
        link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sheet_id}"
        send_message(chat_id, f"✔ Лист {new_title} для «{project_name}» создан: {link}")

    # 4) Добавь КП к RFQ-… (авто-парсер без обязательного двоеточия)
    elif text.lower().startswith("добавь кп к rfq-"):
        lines = text.splitlines()
        # Первый элемент – команда, например "Добавь КП к RFQ-1"
        head = lines[0].strip()
        rfq_label = head.split()[-1].upper()
        data_lines = lines[1:]
        rows = []
        for line in data_lines:
            line = line.strip()
            if not line:
                continue
            # Найти первую вхождение числа (цены)
            m = re.search(r"[\d\.,]+", line)
            if not m:
                continue
            price_start = m.start()
            supplier = line[:price_start].strip(" —-:")
            rest = line[price_start:].strip()
            parts = rest.split()
            price = parts[0]
            terms = " ".join(parts[1:]) if len(parts) > 1 else ""
            rows.append([supplier, price, terms, ""])
        # Вставляем новые строки
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{rfq_label}'!A2",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()
        # Авто-подсветка лучшего
        meta       = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_info = next(s for s in meta["sheets"]
                          if s["properties"]["title"] == rfq_label)
        sheet_id   = sheet_info["properties"]["sheetId"]
        vals       = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{rfq_label}'!B2:B"
        ).execute().get("values", [])
        prices = []
        for r in vals:
            m = re.search(r"[\d\.,]+", r[0]) if r else None
            prices.append(float(m.group().replace(",", ".")) if m else float('inf'))
        best_idx = prices.index(min(prices)) if prices else None
        # Собираем запросы для сброса и подсветки
        requests_body = {"requests": []}
        if prices:
            # сброс фона
            requests_body["requests"].append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": 1 + len(prices),
                        "startColumnIndex": 0,
                        "endColumnIndex": 4
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": None}},
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })
            # подсветка лучшей
            requests_body["requests"].append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1 + best_idx,
                        "endRowIndex": 2 + best_idx,
                        "startColumnIndex": 0,
                        "endColumnIndex": 4
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": {
                        "red": 0.8, "green": 1.0, "blue": 0.8
                    }}},
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })
            service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=requests_body
            ).execute()
        send_message(chat_id, f"➡ Добавлено {len(rows)} строк и лучший вариант подсвечен в {rfq_label}.")

    # 5) всё остальное — эхо
    else:
        send_message(chat_id, f"Получено: {text}")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
