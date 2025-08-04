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
from gpt import translate_and_structure_boq, compare_offer_with_boq

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

# === Helper: Read Registry ===
def read_registry():
    try:
        sheet = client.open_by_key(TEMPLATE_FILE_ID).worksheet(REGISTRY_SHEET_NAME)
        records = sheet.get_all_records()
        return records
    except Exception as e:
        print("Error reading registry:", e)
        return []

# === Helper: Add to Registry ===
def add_project_to_registry(name):
    registry = client.open_by_key(TEMPLATE_FILE_ID).worksheet(REGISTRY_SHEET_NAME)
    existing = registry.col_values(1)
    if name in existing:
        return False
    registry.append_row([name])
    return True

# === Helper: Create Project Sheet ===
def create_project_sheet(project_name):
    try:
        copied = drive_service.files().copy(
            fileId=TEMPLATE_FILE_ID,
            body={"name": project_name}
        ).execute()
        file_id = copied["id"]
        sheet = client.open_by_key(TEMPLATE_FILE_ID)
        sheet.add_worksheet(title=project_name, rows="100", cols="20")
        return sheet.worksheet(project_name)
    except HttpError as e:
        raise Exception(f"Google Drive Error: {e}")

# === Telegram Handlers ===
@bot.message_handler(commands=['start'])
def handle_start(message: Message):
    bot.send_message(message.chat.id, "👋 Привет! Я бот SupplyPilot.\n\n📥 Отправь мне:\n— Excel файл (BOQ) для перевода и структуры\n— PDF файл с КП для сравнения с BOQ")

@bot.message_handler(content_types=['document'])
def handle_docs(message: Message):
    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    filename = message.document.file_name.lower()

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        project_name = os.path.splitext(message.document.file_name)[0].strip()
        success = add_project_to_registry(project_name)
        if not success:
            bot.send_message(message.chat.id, f"⚠️ Проект '{project_name}' уже существует в реестре.")
            return

        sheet = create_project_sheet(project_name)
        df = pd.read_excel(io.BytesIO(downloaded))
        translated_df = translate_and_structure_boq("\n".join(df.iloc[:, 0].astype(str)))
        sheet.update([translated_df.columns.values.tolist()] + translated_df.values.tolist())
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
        boq_df = pd.DataFrame(sheet.get_all_values())[1:]
        boq_df.columns = boq_df.iloc[0]
        boq_df = boq_df[1:]

        offer_df = compare_offer_with_boq(io.BytesIO(pdf_buffer[message.chat.id]).read().decode(errors="ignore"), boq_df)

        start_col = chr(66 + len(sheet.row_values(1)) // 3 * 3)
        sheet.update(f"{start_col}1", [[project_name]])
        sheet.update(f"{start_col}2", [["Unit Price", "Total Price", "Notes"]])

        for i, row in offer_df.iterrows():
            unit_price = float(row['Unit Price']) if row['Unit Price'] else 0
            qty = float(boq_df[boq_df['BOQ Item'] == row['BOQ Match']]["Qty"].values[0]) if 'Qty' in boq_df.columns else 1
            total = unit_price * qty
            note = "✅" if row['BOQ Match'] != "Not matched" else "❗ Not matched"
            sheet.update(f"{start_col}{i+3}", [[unit_price, total, note]])

        bot.send_message(message.chat.id, f"✅ КП добавлено в проект '{project_name}'.")
        user_states.pop(message.chat.id, None)
        pdf_buffer.pop(message.chat.id, None)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}")

# === Start Polling ===
print("🤖 Бот запущен...")
bot.infinity_polling()
