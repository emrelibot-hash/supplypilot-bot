import telebot
import os
import tempfile
import openai
import pandas as pd
from gpt import extract_boq_using_gpt, translate_text
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# === CONFIG ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"

bot = telebot.TeleBot(BOT_TOKEN)

# === GOOGLE API ===
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)
sheet = service.spreadsheets()

# === HELPERS ===
def add_project_to_registry(project_name):
    registry_range = "Registry!A:A"
    existing = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=registry_range).execute().get("values", [])
    existing_flat = [r[0] for r in existing]
    if project_name not in existing_flat:
        sheet.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="Registry!A:B",
            valueInputOption="RAW",
            body={"values": [[project_name, project_name]]}
        ).execute()

def create_project_sheet(project_name):
    sheet_body = {
        "requests": [{
            "addSheet": {
                "properties": {"title": project_name[:100]}
            }
        }]
    }
    try:
        service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=sheet_body).execute()
    except Exception as e:
        print("Sheet creation error:", e)

def write_boq_to_sheet(project_name, df):
    values = [df.columns.tolist()] + df.values.tolist()
    range_ = f"'{project_name}'!A1"
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_,
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

# === TELEGRAM HANDLERS ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет! Отправь мне BOQ-файл Excel (.xlsx), и я добавлю его в таблицу после обработки GPT.")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
            f.write(downloaded_file)
            filepath = f.name

        project_name = os.path.splitext(message.document.file_name)[0]
        df_boq = extract_boq_using_gpt(filepath)

        if df_boq is None or df_boq.empty:
            bot.reply_to(message, "❌ GPT не смог извлечь данные из файла.")
            return

        # Добавляем в таблицу
        add_project_to_registry(project_name)
        create_project_sheet(project_name)
        write_boq_to_sheet(project_name, df_boq)
        bot.reply_to(message, f"✅ Проект «{project_name}» добавлен в Google Sheet.")

    except Exception as e:
        print("Ошибка:", e)
        bot.reply_to(message, "⚠️ Произошла ошибка при обработке файла.")

# === RUN ===
bot.infinity_polling()
