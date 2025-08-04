import os
import io
import telebot
import openai
import gspread
import base64
import json
import pandas as pd
import re
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials
from telebot.types import Message, InputFile
from gpt import translate_text, extract_supplier_name_from_pdf, compare_offer_with_boq

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TEMPLATE_FILE_ID = os.getenv("GOOGLE_SHEET_ID")
REGISTRY_SHEET_NAME = os.getenv("REGISTRY_SHEET_NAME", "Registry")

# === Google Auth ===
creds_json = os.getenv("GOOGLE_CREDS_JSON")
creds_dict = json.loads(creds_json)
creds = Credentials.from_service_account_info(creds_dict, scopes=[
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
])
client = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)

# === Telegram Init ===
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# === Bot State ===
user_states = {}
pdf_buffer = {}

# === Helpers ===
def read_registry():
    try:
        sheet = client.open_by_key(TEMPLATE_FILE_ID).worksheet(REGISTRY_SHEET_NAME)
        return sheet.col_values(1)[1:]  # skip header
    except Exception as e:
        print("Error reading registry:", e)
        return []

def add_project_to_registry(name):
    registry = client.open_by_key(TEMPLATE_FILE_ID).worksheet(REGISTRY_SHEET_NAME)
    registry.append_row([name])
    return True

def create_project_sheet(project_name):
    spreadsheet = client.open_by_key(TEMPLATE_FILE_ID)
    spreadsheet.add_worksheet(title=project_name, rows="100", cols="20")
    return spreadsheet.worksheet(project_name)

def process_boq_dataframe(df):
    if df.empty:
        return None

    df.columns = [str(c).strip() for c in df.columns]
    if 'Description' not in df.columns:
        df.rename(columns={df.columns[1]: 'Description'}, inplace=True)
    if 'Qty' not in df.columns:
        df.rename(columns={df.columns[2]: 'Qty'}, inplace=True)
    if 'Means of Unit' not in df.columns:
        df.rename(columns={df.columns[3]: 'Means of Unit'}, inplace=True)

    df['Description Original'] = df['Description']
    df['Description Translated'] = df['Description'].apply(
        lambda x: translate_text(str(x)) if not re.search(r'[а-яА-Яa-zA-Z]', str(x)) else str(x)
    )

    return df[['Description Original', 'Description Translated', 'Qty', 'Means of Unit']]

@bot.message_handler(commands=['start'])
def handle_start(message: Message):
    bot.send_message(message.chat.id, "👋 Привет! Я бот SupplyPilot.\n\n📥 Отправь мне:\n— Excel файл (BOQ) для перевода и структуры\n— PDF файл с КП для сравнения с BOQ")

@bot.message_handler(content_types=['document'])
def handle_docs(message: Message):
    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    filename = message.document.file_name.lower()

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        xls = pd.ExcelFile(io.BytesIO(downloaded))
        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name)
            project_base = os.path.splitext(message.document.file_name)[0].strip()
            project_name = f"{project_base} - {sheet_name}"

            add_project_to_registry(project_name)
            sheet = create_project_sheet(project_name)
            structured_df = process_boq_dataframe(df)

            if structured_df is not None:
                sheet.update([structured_df.columns.values.tolist()] + structured_df.values.tolist())

        bot.send_message(message.chat.id, f"✅ BOQ '{message.document.file_name}' обработан и добавлен в систему.")

    elif filename.endswith(".pdf"):
        projects = read_registry()
        if not projects:
            bot.send_message(message.chat.id, "❌ Нет доступных проектов. Сначала загрузите BOQ.")
            return

        user_states[message.chat.id] = 'waiting_for_project_selection'
        pdf_buffer[message.chat.id] = downloaded
        options = [f"{i+1}. {name}" for i, name in enumerate(projects)]
        bot.send_message(message.chat.id, "📝 Выберите проект для привязки КП:\n" + "\n".join(options))

@bot.message_handler(func=lambda msg: user_states.get(msg.chat.id) == 'waiting_for_project_selection')
def handle_project_selection(message: Message):
    try:
        index = int(message.text.strip()) - 1
        projects = read_registry()
        project_name = projects[index]

        sheet = client.open_by_key(TEMPLATE_FILE_ID).worksheet(project_name)
        values = sheet.get_all_values()
        boq_df = pd.DataFrame(values[1:], columns=values[0])

        offer_text = io.BytesIO(pdf_buffer[message.chat.id]).read().decode(errors="ignore")
        offer_df = compare_offer_with_boq(offer_text, boq_df)
        supplier_name = extract_supplier_name_from_pdf(io.BytesIO(pdf_buffer[message.chat.id]))

        existing_cols = len(values[0])
        col_offset = (existing_cols // 3) * 3 + 1
        start_col = chr(65 + col_offset)

        sheet.update(f"{start_col}1", [[supplier_name]])
        sheet.update(f"{start_col}2", [["Unit Price", "Total Price", "Notes"]])

        for i, row in offer_df.iterrows():
            match = row['BOQ Match']
            if match != "Not matched" and match in boq_df['Description Original'].values:
                qty = float(boq_df.loc[boq_df['Description Original'] == match, 'Qty'].values[0])
                unit_price = float(row['Unit Price']) if row['Unit Price'] else 0
                total = unit_price * qty
                note = "✅"
            else:
                unit_price, total, note = "", "", "❗ Not matched"
            sheet.update(f"{start_col}{i+3}", [[unit_price, total, note]])

        bot.send_message(message.chat.id, f"✅ КП добавлено в проект '{project_name}'.")
        user_states.pop(message.chat.id, None)
        pdf_buffer.pop(message.chat.id, None)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")

print("🤖 Бот запущен...")
bot.infinity_polling()
