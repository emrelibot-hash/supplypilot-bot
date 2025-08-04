import os
import io
import json
import openai
import base64
import telebot
import gspread
import mimetypes
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from telebot.types import Message, Document

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
TEMPLATE_FILE_ID = "1zKd3hq7R-CI_i0azdZsdIPihBNT-6BlhADW0M0eiGpo"
REGISTRY_SHEET_NAME = "Registry"

openai.api_key = OPENAI_API_KEY
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Авторизация в Google API
creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    scopes=[
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
)
client = gspread.authorize(creds)
drive_service = build("drive", "v3", credentials=creds)

def ensure_registry():
    try:
        return client.open_by_key(GOOGLE_SHEET_ID).worksheet(REGISTRY_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        return sheet.add_worksheet(title=REGISTRY_SHEET_NAME, rows="100", cols="3")

def get_next_boq_code():
    registry = ensure_registry()
    existing = registry.col_values(1)[1:]  # skip header
    numbers = [int(row.replace("BOQ-", "")) for row in existing if row.startswith("BOQ-")]
    next_number = max(numbers, default=0) + 1
    return f"BOQ-{next_number:03d}"

def copy_template_sheet(new_title):
    copied_file = drive_service.files().copy(
        fileId=TEMPLATE_FILE_ID,
        body={"name": new_title}
    ).execute()
    return copied_file["id"]
@bot.message_handler(commands=["start"])
def handle_start(message: Message):
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я Вика.\n\n" +
        "📥 Отправь мне:\n— Excel файл (BOQ) для перевода и структуры\n— PDF файл с КП для сравнения с BOQ\n\n" +
        "Все таблицы будут добавлены в Google Sheets автоматически."
    )
@bot.message_handler(content_types=["document"])
def handle_docs(message: Message):
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        mime_type, _ = mimetypes.guess_type(message.document.file_name)

        if message.document.file_name.endswith(".xlsx"):
            boq_code = get_next_boq_code()
            new_sheet_id = copy_template_sheet(boq_code)

            registry = ensure_registry()
            registry.append_row([boq_code, new_sheet_id, message.document.file_name])

            bot.reply_to(message, f"✅ BOQ-файл получен и добавлен как проект *{boq_code}*.", parse_mode="Markdown")

        elif message.document.file_name.endswith(".pdf"):
            bot.reply_to(message, "📌 Ваша PDF получена. Сейчас запрошу, к какому проекту её привязать...")
            # Здесь должна быть логика выбора проекта

        else:
            bot.reply_to(message, "⚠️ Поддерживаются только файлы Excel (.xlsx) и PDF.")

    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка: {e}")

if __name__ == "__main__":
    print("Бот запущен")
    bot.infinity_polling()
