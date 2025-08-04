import os
import io
import telebot
import openai
import gspread
import base64
import json
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials
from telebot.types import Message, InputFile
from gpt import translate_and_structure_boq, compare_offer_with_boq, extract_supplier_name_from_pdf

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

# === Registry ===
def read_registry():
    try:
        sheet = client.open_by_key(TEMPLATE_FILE_ID).worksheet(REGISTRY_SHEET_NAME)
        return sheet.get_all_records()
    except Exception as e:
        print("Error reading registry:", e)
        return []

def add_project_to_registry(project_name):
    try:
        sheet = client.open_by_key(TEMPLATE_FILE_ID).worksheet(REGISTRY_SHEET_NAME)
        sheet.append_row([project_name])
    except Exception as e:
        print("Failed to write to registry:", e)

# === Create Sheet ===
def create_project_sheet(sheet_title):
    try:
        sheet = client.open_by_key(TEMPLATE_FILE_ID)
        return sheet.add_worksheet(title=sheet_title, rows="100", cols="20")
    except Exception as e:
        raise Exception(f"Ошибка создания листа: {e}")

# === Telegram Handlers ===
@bot.message_handler(commands=['start'])
def handle_start(message: Message):
    bot.send_message(message.chat.id, "👋 Привет! Я Вика.\n\n📥 Отправь мне:\n— Excel файл (BOQ) для перевода и структуры\n— PDF файл с КП для сравнения с BOQ")

@bot.message_handler(content_types=['document'])
def handle_docs(message: Message):
    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    filename = message.document.file_name.lower()

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        project_name = os.path.splitext(message.document.file_name)[0].strip()

        xls = pd.ExcelFile(io.BytesIO(downloaded))
        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                translated_df = translate_and_structure_boq("\n".join(df.iloc[:, 0].astype(str)))

                title = f"{project_name} - {sheet_name}" if len(xls.sheet_names) > 1 else project_name
                create_project_sheet(title)
                add_project_to_registry(title)

                worksheet = client.open_by_key(TEMPLATE_FILE_ID).worksheet(title)
                worksheet.update([translated_df.columns.values.tolist()] + translated_df.values.tolist())
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Ошибка при обработке листа {sheet_name}: {str(e)}")

        bot.send_message(message.chat.id, f"✅ BOQ '{project_name}' добавлен в систему.")

    elif filename.endswith(".pdf"):
        projects = read_registry()
        if not projects:
            bot.send_message(message.chat.id, "❌ Нет доступных проектов. Сначала загрузите BOQ.")
            return

        user_states[message.chat.id] = 'waiting_for_project_selection'
        pdf_buffer[message.chat.id] = downloaded

        options = [f"{i+1}. {p[''] if '' in p else list(p.values())[0]}" for i, p in enumerate(projects)]
        bot.send_message(message.chat.id, "📝 Выберите проект для привязки КП:\n" + "\n".join(options))

@bot.message_handler(func=lambda msg: user_states.get(msg.chat.id) == 'waiting_for_project_selection')
def handle_project_selection(message: Message):
    try:
        index = int(message.text.strip()) - 1
        projects = read_registry()
        project_name = list(projects[index].values())[0]

        sheet = client.open_by_key(TEMPLATE_FILE_ID).worksheet(project_name)
        boq_df = pd.DataFrame(sheet.get_all_values())
        boq_df.columns = boq_df.iloc[0]
        boq_df = boq_df[1:]

        pdf_bytes = pdf_buffer[message.chat.id]
        supplier = extract_supplier_name_from_pdf(io.BytesIO(pdf_bytes))

        offer_df = compare_offer_with_boq(pdf_bytes.decode(errors="ignore"), boq_df)

        col_start = 1 + len(sheet.row_values(2))
        sheet.update_cell(1, col_start, supplier)
        sheet.update_cell(2, col_start, "Unit Price")
        sheet.update_cell(2, col_start + 1, "Total Price")
        sheet.update_cell(2, col_start + 2, "Notes")

        for i, row in offer_df.iterrows():
            unit_price = float(row['Unit Price']) if row['Unit Price'] else 0
            boq_match = row['BOQ Match']
            try:
                qty = float(boq_df.loc[boq_df['BOQ Item'] == boq_match]['Q-ty'].values[0])
            except:
                qty = 1
            total_price = unit_price * qty
            note = "✅" if row['Notes'] == "Match" else "❗ " + row['Notes']
            sheet.update_cell(i + 3, col_start, unit_price)
            sheet.update_cell(i + 3, col_start + 1, total_price)
            sheet.update_cell(i + 3, col_start + 2, note)

        bot.send_message(message.chat.id, f"✅ КП добавлено в проект '{project_name}'.")
        user_states.pop(message.chat.id, None)
        pdf_buffer.pop(message.chat.id, None)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")

# === Start Polling ===
print("🤖 Бот запущен...")
bot.infinity_polling()
