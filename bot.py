import os, json, logging
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters, CallbackContext
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Логирование
logging.basicConfig(level=logging.INFO)

# Токен бота и доступ к Google
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CREDS_JSON = json.loads(os.getenv("GOOGLE_CREDS_JSON"))

# ID твоей Google-таблицы (из URL)
SPREADSHEET_ID = "1GL0_wzT3OaFBPQk6opiDaSdel4uVzpr_lcTbJtBNlxk"
# Имя листа, куда писать (обычно Sheet1)
SHEET_NAME = "Sheet1"

# Инициализация бота и Flask
bot = Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot, None, workers=0, use_context=True)

# Авторизация в Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON, scopes=SCOPES)
sheets_service = build('sheets', 'v4', credentials=creds)

# /start
def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Привет, Низами! Бот запущен и готов к работе.")

# /test — проверка Google Sheets
def test(update: Update, context: CallbackContext):
    body = {"values": [["✅ Bot connected"]]}
    sheets_service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        body=body
    ).execute()
    update.message.reply_text("✅ Google Sheets обновлены.")

# Эхо-хендлер на все остальные сообщения
def echo(update: Update, context: CallbackContext):
    update.message.reply_text(f"Получено: {update.message.text}")

# Регистрируем хендлеры
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("test", test))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))

# Webhook-роут
@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
