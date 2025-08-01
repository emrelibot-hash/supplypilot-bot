import os
import json
import logging
from flask import Flask, request
import telegram
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Настройки
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_CREDS_JSON = json.loads(os.environ.get("GOOGLE_CREDS_JSON"))

bot = telegram.Bot(token=TELEGRAM_TOKEN)
app = Flask(__name__)

# Авторизация в Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = service_account.Credentials.from_service_account_info(GOOGLE_CREDS_JSON, scopes=SCOPES)
sheets_service = build('sheets', 'v4', credentials=creds)

@app.route("/webhook", methods=["POST"])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    chat_id = update.message.chat.id
    text = update.message.text

    # Пример ответа на текстовое сообщение
    if text.lower().startswith("hello") or text.lower().startswith("/start"):
        bot.send_message(chat_id=chat_id, text="👋 Привет! Бот работает. Готов к работе.")
    else:
        bot.send_message(chat_id=chat_id, text=f"Получено сообщение: {text}")

    return 'ok'
