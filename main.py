import telebot
import os
import pandas as pd
import tempfile
import re
from gpt import translate_and_structure_boq, detect_boq_structure
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from gpt import extract_supplier_name_from_pdf

# === CONFIG ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
SPREADSHEET_ID = "1zKd3hq7R-CI_i0azdZsdIPihBNT-6BlhADW0M0eiGpo"
TEMPLATE_SHEET = "Template"

# === GOOGLE API SETUP ===
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = "credentials.json"
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)
sheet = service.spreadsheets()

# === HELPERS ===
def add_project_to_registry(project_name):
    registry_range = "Registry!A:A"
    existing = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=registry_range).execute().get("values", [])
    existing_flat = [r[0] for r in existing]
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
                "properties": {"title": project_name[:100]}  # title max 100 chars
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
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
        f.write(downloaded_file)
        filepath = f.name

    project_name = os.path.splitext(message.document.file_name)[0]
    try:
        xls = pd.ExcelFile(filepath)
        all_data = pd.DataFrame()

        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name)
            if df.empty:
                continue

            structure = detect_boq_structure(df)
            if not structure['Description'] or not structure['Qty'] or not structure['Means of Unit']:
                continue

            desc_col = structure['Description']
            qty_col = structure['Qty']
            unit_col = structure['Means of Unit']

            sub_df = df[[desc_col, qty_col, unit_col]].copy()
            sub_df.columns = ['Description Original', 'Qty', 'Means of Unit']

            sub_df['Description Translated'] = sub_df['Description Original'].apply(
                lambda x: x if re.search(r'[а-яА-Яa-zA-Z]', str(x)) else translate_and_structure_boq(str(x))
            )

            all_data = pd.concat([all_data, sub_df], ignore_index=True)

        if all_data.empty:
            bot.reply_to(message, "❌ Не удалось извлечь данные из таблицы.")
            return

        add_project_to_registry(project_name)
        create_project_sheet(project_name)
        write_boq_to_sheet(project_name, all_data)
        bot.reply_to(message, f"✅ Проект «{project_name}» добавлен.")
    except Exception as e:
        print("Ошибка обработки:", e)
        bot.reply_to(message, "⚠️ Ошибка при обработке файла.")

# === START ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет! Отправь мне файл BOQ в формате Excel (.xlsx), и я добавлю его в таблицу.")

bot.infinity_polling()
