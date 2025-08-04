import os
import json
import telebot
import openai
import fitz  # PyMuPDF
import tempfile
import pandas as pd
import gspread
from flask import Flask, request
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from httplib2 import Http

# --- Config ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
TEMPLATE_FILE_ID = "1zKd3hq7R-CI_i0azdZsdIPihBNT-6BlhADW0M0eiGpo"  # шаблон для копирования
REGISTRY_SHEET_NAME = "Registry"

# --- Clients ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai.api_key = OPENAI_API_KEY

# --- Google auth ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDS_JSON, scope)
client = gspread.authorize(creds)
drive_service = creds.authorize(Http())

# --- Flask (for webhook if needed) ---
app = Flask(__name__)

# --- Helpers ---
def ensure_registry():
    try:
        return client.open_by_key(GOOGLE_SHEET_ID).worksheet(REGISTRY_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return client.open_by_key(GOOGLE_SHEET_ID).add_worksheet(title=REGISTRY_SHEET_NAME, rows="100", cols="3")

def get_next_boq_code():
    registry = ensure_registry()
    existing_codes = registry.col_values(1)
    numbers = [int(code.replace("BOQ-", "")) for code in existing_codes if code.startswith("BOQ-")]
    next_num = max(numbers) + 1 if numbers else 1
    return f"BOQ-{next_num:03}"

def copy_template_sheet(title):
    try:
        copied_file = drive_service.files().copy(
            fileId=TEMPLATE_FILE_ID,
            body={"name": title}
        ).execute()
        return copied_file["id"]
    except HttpError as error:
        print(f"An error occurred while copying the template: {error}")
        return None

def register_project(boq_code, file_id):
    registry = ensure_registry()
    registry.append_row([boq_code, f"https://docs.google.com/spreadsheets/d/{file_id}", "RFQ"])

# --- Handlers ---
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        file_ext = os.path.splitext(message.document.file_name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            tmp.write(downloaded_file)
            tmp_path = tmp.name

        if file_ext == '.xlsx':
            boq_code = get_next_boq_code()
            new_sheet_id = copy_template_sheet(boq_code)
            register_project(boq_code, new_sheet_id)
            bot.reply_to(message, f"✅ Создан проект {boq_code}. Таблица: https://docs.google.com/spreadsheets/d/{new_sheet_id}")
        elif file_ext == '.pdf':
            # Пока заглушка — ожидается реализация привязки к существующему BOQ
            bot.reply_to(message, "❓ Пожалуйста, укажи, к какому проекту (BOQ) привязать этот файл. Скоро появится меню выбора.")
        else:
            bot.reply_to(message, "⚠️ Поддерживаются только .xlsx и .pdf файлы.")

    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка: {str(e)}")

# --- Run bot ---
if __name__ == "__main__":
    bot.polling(none_stop=True)
