import os
import json
import logging

from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Логирование
logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CREDS_JSON = json.loads(os.getenv("GOOGLE_CREDS_JSON"))

# Инициализируем бота и Flask
bot = Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)

# Авторизация Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON, scopes=SCOPES)
sheets_service = build('sheets', 'v4', credentials=creds)

# Диспетчер для команд
dispatcher = Dispatcher(bot, None, workers=0, use_context=True)

def start(update: Update, context):
    update.message.reply_text("👋 Привет, Низами. Бот запущен и готов к работе!")

def echo(update: Update, context):
    update.message.reply_text(f"Получил: {update.message.text}")

# Регистрируем обработчики
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, bot)
    dispatcher.process_update(update)
    return "OK"

if __name__ == "__main__":
    # Если нужен polling (для тестов), можно раскомментировать:
    # from telegram.ext import Updater
    # updater = Updater(TELEGRAM_TOKEN, use_context=True)
    # updater.start_polling()
    # updater.idle()
    # Но мы будем использовать webhook:
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
