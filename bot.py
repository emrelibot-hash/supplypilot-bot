import os
import re
import requests
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Настройки ---
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
API_URL          = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
SPREADSHEET_ID   = "1GL0_wzT3OaFBPQk6opiDaSdel4uVzpr_lcTbJtBNlxk"
CREDS_PATH       = os.getenv("GOOGLE_CREDS_PATH", "vika-bot.json")
EXCHANGE_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"

# --- Константы ---
INCOTERMS       = {"EXW","FCA","FAS","FOB","CFR","CIF","CPT","CIP","DAT","DAP","DDP"}
UNITS           = {"kg","g","ton","t","unit","pcs","piece","m","m2","m3"}
CURRENCIES      = {"USD","EUR","AZN","RUB","GEL"}
CREATE_TRIGGERS = [
    "создай ",
    "сделай ",
    "создай таблицу ",
    "сделай сравнительную таблицу "
]

# кеш курсов
exchange_rates = {}

def get_usd_rate(cur: str) -> float:
    cur = cur.upper()
    if cur == "USD":
        return 1.0
    global exchange_rates
    if not exchange_rates:
        resp = requests.get(EXCHANGE_API_URL).json()
        exchange_rates.update(resp.get("rates", {}))
    return exchange_rates.get(cur, 1.0)

# --- Инициализация Google Sheets API ---
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
    text    = (msg.get("text", "") or "").strip()

    if not chat_id:
        return "ok", 200

    # 1) /start
    if text.startswith("/start"):
        send_message(chat_id, "👋 Привет! Бот готов к работе.")
        return "ok", 200

    # 2) /test
    if text.startswith("/test"):
        meta  = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        title = meta["sheets"][0]["properties"]["title"]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{title}'!A1",
            valueInputOption="RAW",
            body={"values":[["✅ Bot connected"]]}
        ).execute()
        send_message(chat_id, f"✅ Лист «{title}» обновлён.")
        return "ok", 200

    lower = text.lower()

    # 3) Создать новый RFQ-лист по любому из триггеров
    for trig in CREATE_TRIGGERS:
        if lower.startswith(trig):
            project_name = text[len(trig):].strip()
            meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
            existing = [
                s["properties"]["title"]
                for s in meta["sheets"]
                if s["properties"]["title"].startswith("RFQ-")
            ]
            idx       = len(existing) + 1
            new_title = f"RFQ-{idx}"
            resp = service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":new_title}}}]}
            ).execute()
            sid = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
            headers = [["Поставщик","Цена","Ед.изм.","Incoterm","Условия","Комментарий"]]
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{new_title}'!A1",
                valueInputOption="RAW",
                body={"values":headers}
            ).execute()
            link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sid}"
            send_message(chat_id, f"✔ Лист {new_title} для «{project_name}» создан: {link}")
            return "ok", 200

    # 4) Добавить КП к RFQ… (гибкий триггер + парсер + конвертация + авто-подсветка)
    m = re.search(r'добав(?:ь|ить).*?rfq[\s\-]?(\d+)', lower)
    if m:
        num       = m.group(1)
        rfq_label = f"RFQ-{num}"

        # остаток после префикса
        body = text[m.end():].strip()
        # разбиваем на строки или зафиксируем одну строку
        if "\n" in body:
            lines = [l for l in body.splitlines() if l.strip()]
        else:
            lines = [body] if body else []

        rows      = []
        usd_values= []
        seen      = set()
        # шаблон для цены+валюты+единицы
        pat = re.compile(
            rf'(?P<price>[\d\.,]+)\s*(?P<currency>{"|".join(CURRENCIES)})?'
            rf'(?:\/\s*(?P<unit>{"|".join(UNITS)}))?',
            flags=re.IGNORECASE
        )

        for ln in lines:
            l = ln.strip()
            if not l:
                continue
            pm = pat.search(l)
            if not pm:
                continue
            start, end = pm.span()
            supplier = l[:start].strip("—-: ").title()
            if supplier.lower() in seen:
                continue
            seen.add(supplier.lower())

            price_num = pm.group("price").replace(",", ".")
            cur       = (pm.group("currency") or "USD").upper()
            unit      = (pm.group("unit") or "").lower()
            rate      = get_usd_rate(cur)
            usd_val   = float(price_num) / rate
            usd_values.append(usd_val)

            tail  = l[end:].strip("—-: ")
            parts = tail.split()
            inc   = next((p.upper() for p in parts if p.upper() in INCOTERMS), "")
            if inc:
                parts.remove(inc)
            cond  = " ".join(parts)

            price_cell = f"{price_num} {cur}"
            rows.append([supplier, price_cell, unit, inc, cond, ""])

        if not rows:
            send_message(chat_id, "❗ Не удалось распознать ни одной строки.")
            return "ok", 200

        # вставка данных
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{rfq_label}'!A2",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()

        # подсветка лучшего
        best_idx = usd_values.index(min(usd_values))
        meta     = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sid      = next(
            s["properties"]["sheetId"]
            for s in meta["sheets"]
            if s["properties"]["title"] == rfq_label
        )
        reqs = [
            {"repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 1,
                    "endRowIndex": 1 + len(usd_values),
                    "startColumnIndex": 0,
                    "endColumnIndex": 6
                },
                "cell": {"userEnteredFormat": {"backgroundColor": None}},
                "fields": "userEnteredFormat.backgroundColor"
            }},
            {"repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 1 + best_idx,
                    "endRowIndex": 2 + best_idx,
                    "startColumnIndex": 0,
                    "endColumnIndex": 6
                },
                "cell": {"userEnteredFormat": {"backgroundColor":{
                    "red":0.8,"green":1.0,"blue":0.8
                }}},
                "fields": "userEnteredFormat.backgroundColor"
            }}
        ]
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": reqs}
        ).execute()

        send_message(chat_id,
            f"➡ Добавлено {len(rows)} строк, лучший вариант (строка {best_idx+2}) подсвечен в {rfq_label}.")
        return "ok", 200

    # 5) Эхо на всё остальное
    send_message(chat_id, f"Получено: {text}")
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
