import os
import io
import re
import fitz  # PyMuPDF
import telebot
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

# Telegram
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Google Sheets Auth
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(eval(GOOGLE_CREDS_JSON), scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

# Sheet with project registry
REGISTRY_SHEET_NAME = "Registry"

# Global session storage
user_sessions = {}

# Language detection and translation helpers (optional)
def extract_prices(text):
    matches = re.findall(r'(.*?)\s+(\d+[.,]?\d*)\s*(USD|EUR|GEL)?', text)
    offers = []
    for match in matches:
        description = match[0].strip()
        price = match[1].replace(',', '.')
        currency = match[2] or 'USD'
        offers.append((description, float(price), currency))
    return offers

# Handlers
@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(message.chat.id, "👋 Привет! Отправь Excel с BOQ или PDF с КП. Всё остальное я сделаю сам.")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    file_info = bot.get_file(message.document.file_id)
    file = bot.download_file(file_info.file_path)

    if message.document.file_name.endswith(".pdf"):
        text = extract_text_from_pdf(file)
        user_sessions[message.chat.id] = {'pdf_text': text}
        ask_project_selection(message)
    elif message.document.file_name.endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(file))
        boq_code = df.columns[0]
        if boq_code not in [ws.title for ws in spreadsheet.worksheets()]:
            new_ws = spreadsheet.add_worksheet(title=boq_code, rows="100", cols="20")
        else:
            new_ws = spreadsheet.worksheet(boq_code)
        set_with_dataframe(new_ws, df)
        register_project(boq_code)
        bot.send_message(message.chat.id, f"✅ BOQ '{boq_code}' добавлен в систему.")
    else:
        bot.send_message(message.chat.id, "❌ Поддерживаются только PDF и Excel-файлы.")

def extract_text_from_pdf(file_bytes):
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)

def ask_project_selection(message):
    registry = spreadsheet.worksheet(REGISTRY_SHEET_NAME).get_all_records()
    if not registry:
        bot.send_message(message.chat.id, "❌ Нет доступных проектов. Сначала загрузите BOQ.")
        return
    text = "📋 В какой проект загрузить это КП?\n"
    for idx, row in enumerate(registry, 1):
        text += f"{idx}. {row['Code']} – {row['Name']}\n"
    bot.send_message(message.chat.id, text)
    bot.register_next_step_handler(message, handle_project_selection)

def handle_project_selection(message):
    selection = message.text.strip()
    registry_ws = spreadsheet.worksheet(REGISTRY_SHEET_NAME)
    registry = registry_ws.get_all_records()

    selected = None
    for idx, row in enumerate(registry, 1):
        if selection == str(idx) or selection.lower() in row['Name'].lower():
            selected = row
            break

    if not selected:
        bot.send_message(message.chat.id, "❌ Не удалось найти проект. Попробуйте снова.")
        return ask_project_selection(message)

    boq_code = selected['Code']
    boq_ws = spreadsheet.worksheet(boq_code)

    text = user_sessions[message.chat.id]['pdf_text']
    offers = extract_prices(text)

    start_row = len(boq_ws.get_all_values()) + 2
    boq_ws.update(f"A{start_row}", [[f"Supplier: from PDF"]])
    for i, (desc, price, currency) in enumerate(offers):
        boq_ws.update(f"A{start_row + i + 1}", [[desc, price, price, currency]])

    bot.send_message(message.chat.id, f"✅ КП добавлено в проект '{boq_code}'.")

def register_project(code):
    registry_ws = spreadsheet.worksheet(REGISTRY_SHEET_NAME)
    all_rows = registry_ws.get_all_values()
    existing_codes = [row[0] for row in all_rows[1:]] if len(all_rows) > 1 else []
    if code not in existing_codes:
        registry_ws.append_row([code, f"Project {code}"])

bot.polling()
