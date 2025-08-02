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
    "сделай сравнительную таблицу ",
    "добавь таблицу "
]

exchange_rates = {}

def get_usd_rate(cur: str) -> float:
    cur = cur.upper()
    if cur == "USD": return 1.0
    global exchange_rates
    if not exchange_rates:
        exchange_rates.update(requests.get(EXCHANGE_API_URL).json().get("rates", {}))
    return exchange_rates.get(cur, 1.0)

# Инициализация Google Sheets API
creds   = service_account.Credentials.from_service_account_file(
    CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]
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
    text    = (msg.get("text") or "").strip()
    lower   = text.lower()

    if not chat_id:
        return "ok", 200

    # /start
    if lower.startswith("/start"):
        send_message(chat_id, "👋 Здравствуй, милый! Что сделать для тебя? ")
        return "ok", 200

    # /test
    if lower.startswith("/test"):
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

    # Создание RFQ-листа + мгновенное заполнение (если КП в том же сообщении)
    for trig in CREATE_TRIGGERS:
        if lower.startswith(trig):
            lines = text.splitlines()
            project = lines[0][len(trig):].strip() or "Без имени"

            # 1) Добавляем лист
            meta     = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
            idx      = len([s for s in meta["sheets"] if s["properties"]["title"].startswith("RFQ-")]) + 1
            title    = f"RFQ-{idx}"
            resp     = service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests":[{"addSheet":{"properties":{"title":title}}}]}
            ).execute()
            sid = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

            # 2) Форматирование шапки
            reqs = [{
                "updateSheetProperties": {
                    "properties": {"sheetId":sid,"gridProperties":{"frozenRowCount":5}},
                    "fields":"gridProperties.frozenRowCount"
                }
            }]
            status = [("Поставлено",{"red":0,"green":1,"blue":0}),
                      ("Ожидается",{"red":1,"green":0.6,"blue":0}),
                      ("В работе",{"red":1,"green":1,"blue":0})]
            cols = 6
            for i,(lbl,color) in enumerate(status):
                reqs += [
                    {"mergeCells":{"range":{"sheetId":sid,"startRowIndex":i,"endRowIndex":i+1,
                                             "startColumnIndex":0,"endColumnIndex":cols},
                                   "mergeType":"MERGE_ALL"}},
                    {"repeatCell":{"range":{"sheetId":sid,"startRowIndex":i,"endRowIndex":i+1,
                                             "startColumnIndex":0,"endColumnIndex":cols},
                                   "cell":{"userEnteredFormat":{"backgroundColor":color}},
                                   "fields":"userEnteredFormat.backgroundColor"}},
                    {"updateCells":{"rows":[{"values":[{"userEnteredValue":{"stringValue":lbl},
                                                          "userEnteredFormat":{"horizontalAlignment":"CENTER"}}]}],
                                    "fields":"userEnteredValue,userEnteredFormat.horizontalAlignment",
                                    "start":{"sheetId":sid,"rowIndex":i,"columnIndex":0}}}
                ]
            # серый фон строк 4 и 5
            for i in (3,4):
                reqs.append({
                    "repeatCell":{"range":{"sheetId":sid,"startRowIndex":i,"endRowIndex":i+1,
                                           "startColumnIndex":0,"endColumnIndex":cols},
                                  "cell":{"userEnteredFormat":{"backgroundColor":{"red":0.6,"green":0.6,"blue":0.6}}},
                                  "fields":"userEnteredFormat.backgroundColor"}
                })
            service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID, body={"requests":reqs}
            ).execute()

            # 3) Шапка таблицы строки 4–5: без жёстких имён поставщиков
            headers = [
                ["№","Продукция","Ед. изм.","Кол-во","Поставщики","",""],
                ["","","","","","",""]
            ]
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{title}'!A4",
                valueInputOption="RAW",
                body={"values":headers}
            ).execute()

            link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sid}"

            # 4) Парсинг КП (если есть)
            kp = lines[1:]
            rows=[]; usd_vals=[]; seen=set()
            pat = re.compile(
                rf'(?P<price>[\d\.,]+)\s*(?P<currency>{"|".join(CURRENCIES)})?'
                rf'(?:\/\s*(?P<unit>{"|".join(UNITS)}))?', flags=re.IGNORECASE
            )
            for ln in kp:
                l=ln.strip()
                m=pat.search(l)
                if not m: continue
                s,e=m.span()
                sup=l[:s].strip("—-: ").title()
                if sup.lower() in seen: continue
                seen.add(sup.lower())
                num=m.group("price").replace(",",".")
                cur=(m.group("currency") or "USD").upper()
                unit=(m.group("unit") or "").lower()
                rate=get_usd_rate(cur); usd=float(num)/rate; usd_vals.append(usd)
                tail=l[e:].strip("—-: ").split()
                inc=next((p.upper() for p in tail if p.upper() in INCOTERMS), "")
                if inc in tail: tail.remove(inc)
                cond=" ".join(tail)
                rows.append([sup, f"{num} {cur}", unit, inc, cond, ""])
            if rows:
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{title}'!A2",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values":rows}
                ).execute()
                bi=usd_vals.index(min(usd_vals))
                # сброс цвета и подсветка
                upd=[{"repeatCell":{"range":{"sheetId":sid,"startRowIndex":1,"endRowIndex":1+len(usd_vals),
                                              "startColumnIndex":0,"endColumnIndex":6},
                                     "cell":{"userEnteredFormat":{"backgroundColor":None}},
                                     "fields":"userEnteredFormat.backgroundColor"}},
                     {"repeatCell":{"range":{"sheetId":sid,"startRowIndex":1+bi,"endRowIndex":2+bi,
                                              "startColumnIndex":0,"endColumnIndex":6},
                                     "cell":{"userEnteredFormat":{"backgroundColor":
                                         {"red":0.8,"green":1.0,"blue":0.8}}},
                                     "fields":"userEnteredFormat.backgroundColor"}}]
                service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID, body={"requests":upd}
                ).execute()
                send_message(chat_id,
                    f"✔ Лист {title} для «{project}» создан: {link}\n➡ Добавлено {len(rows)} строк, "
                    f"лучший вариант (строка {bi+2}) подсвечен.")
                return "ok", 200

            send_message(chat_id, f"✔ Лист {title} для «{project}» создан: {link}")
            return "ok", 200

    # Явная команда «Добавить к RFQ…» (осталась без изменений)
    if re.search(r'добав(?:ь|ить).*?rfq[\s\-]?(\d+)', lower):
        # ваш код добавления
        return "ok", 200

    # Эхо
    send_message(chat_id, f"Получено: {text}")
    return "ok", 200

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
