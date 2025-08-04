import os
import telebot
import fitz  # PyMuPDF
import tempfile
import gspread
import openai
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import set_with_dataframe
from gpt import translate_and_structure_boq, compare_offer_with_boq

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
TEMPLATE_FILE_ID = os.getenv("TEMPLATE_FILE_ID", "1zKd3hq7R-CI_i0azdZsdIPihBNT-6BlhADW0M0eiGpo")
REGISTRY_SHEET_NAME = os.getenv("REGISTRY_SHEET_NAME", "Registry")

# OpenAI setup
openai.api_key = OPENAI_API_KEY

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(eval(GOOGLE_CREDS_JSON), scope)
client = gspread.authorize(creds)
drive_service = creds.authorize(Http())

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Registry utils
def ensure_registry():
    try:
        return client.open_by_key(GOOGLE_SHEET_ID).worksheet(REGISTRY_SHEET_NAME)
    except:
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        return sheet.add_worksheet(title=REGISTRY_SHEET_NAME, rows="100", cols="3")

def get_next_boq_code():
    registry = ensure_registry()
    data = registry.get_all_values()
    existing_codes = [row[0] for row in data[1:]]
    idx = 1
    while True:
        code = f"BOQ-{idx:03d}"
        if code not in existing_codes:
            return code
        idx += 1

def list_projects():
    registry = ensure_registry()
    data = registry.get_all_values()[1:]  # Skip header
    return [(i + 1, row[0], row[1]) for i, row in enumerate(data)]

def get_worksheet_by_code(boq_code):
    return client.open_by_key(GOOGLE_SHEET_ID).worksheet(boq_code)

def copy_template_and_register(name):
    copied = client.copy(file_id=TEMPLATE_FILE_ID, title=name, copy_permissions=True)
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    registry = ensure_registry()
    registry.append_row([name, name])
    return sheet.worksheet(name)

# Handlers
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "👋 Привет! Отправь Excel-файл (BOQ) или PDF с КП")

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    file_info = bot.get_file(message.document.file_id)
    file = bot.download_file(file_info.file_path)
    filename = message.document.file_name

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as temp:
            temp.write(file)
            temp_path = temp.name

        df = pd.read_excel(temp_path)
        boq_code = get_next_boq_code()
        worksheet = copy_template_and_register(boq_code)
        set_with_dataframe(worksheet, df)
        bot.send_message(message.chat.id, f"✅ BOQ сохранён в таблице: {boq_code}")

    elif filename.endswith(".pdf"):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp:
            temp.write(file)
            temp_path = temp.name

        text = extract_text_from_pdf(temp_path)
        offers_text = text[:3000]

        projects = list_projects()
        msg = "📋 Выбери проект для добавления КП:\n"
        for i, code, name in projects:
            msg += f"{i}. {code} — {name}\n"

        sent = bot.send_message(message.chat.id, msg)
        bot.register_next_step_handler(sent, lambda m: handle_project_selection(m, offers_text))

# Обработка выбора проекта
user_pdf_data = {}

def handle_project_selection(message, offers_text):
    try:
        idx = int(message.text.strip()) - 1
        project = list_projects()[idx]
        boq_code = project[1]
        worksheet = get_worksheet_by_code(boq_code)
        boq_df = pd.DataFrame(worksheet.get_all_records())

        offer_df = compare_offer_with_boq(offers_text, boq_df)

        col_start = worksheet.col_count + 1
        worksheet.update_cell(1, col_start, message.from_user.first_name or "Поставщик")
        worksheet.update_cell(2, col_start, "Unit Price")
        worksheet.update_cell(2, col_start + 1, "Total Price")
        worksheet.update_cell(2, col_start + 2, "Notes")

        qty_map = {row["BOQ Item"]: row["Qty"] for _, row in boq_df.iterrows() if "Qty" in row}

        for i, row in offer_df.iterrows():
            boq_item = row["BOQ Match"]
            price = row["Unit Price"]
            total = ""
            notes = ""

            if boq_item in qty_map and price:
                qty = float(qty_map[boq_item])
                total = round(float(price) * qty, 2)
            else:
                notes = "❗ Нет совпадения или количества"

            worksheet.update_cell(i + 3, col_start, price or "")
            worksheet.update_cell(i + 3, col_start + 1, total or "")
            worksheet.update_cell(i + 3, col_start + 2, notes)

        bot.send_message(message.chat.id, f"✅ Данные добавлены в проект {boq_code}")
    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка: {e}")

# PDF extractor
def extract_text_from_pdf(path):
    with fitz.open(path) as doc:
        text = "\n".join(page.get_text() for page in doc)
    return text

bot.polling()
