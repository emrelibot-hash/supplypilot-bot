# main.py
import os
import logging
import telebot
import tempfile
import fitz  # PyMuPDF for PDFs
import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from gspread_dataframe import set_with_dataframe
import pandas as pd
from utils import extract_text_from_excel, extract_text_from_pdf
from gpt import translate_and_structure_boq, compare_offer_with_boq, extract_supplier_offer, update_sheet_with_offer

# Load environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")  # JSON content as string

openai.api_key = OPENAI_API_KEY
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Set up logging
logging.basicConfig(level=logging.INFO)

# Google Sheets auth
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=".json") as f:
    f.write(GOOGLE_CREDS_JSON)
    creds_path = f.name
creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
client = gspread.authorize(creds)

# In-memory state: user_id -> (pdf_path, supplier_text)
pending_pdf = {}

REGISTRY_SHEET_NAME = "Реестр"
def ensure_registry():
    try:
        return client.open_by_key(GOOGLE_SHEET_ID).worksheet(REGISTRY_SHEET_NAME)
    except:
        return client.open_by_key(GOOGLE_SHEET_ID).add_worksheet(title=REGISTRY_SHEET_NAME, rows="100", cols="3")

def get_next_boq_code():
    registry = ensure_registry()
    records = registry.get_all_records()
    last_code = 0
    for row in records:
        if row['Код'].startswith("BOQ-"):
            try:
                num = int(row['Код'].split("-")[1])
                last_code = max(last_code, num)
            except:
                continue
    return f"BOQ-{last_code+1:03d}"

def register_boq(code, filename):
    registry = ensure_registry()
    data = registry.get_all_values()
    if not data:
        registry.append_row(["Код", "Название файла"])
    clean_name = os.path.splitext(filename)[0]
    registry.append_row([code, clean_name])

def get_boq_options():
    registry = ensure_registry()
    records = registry.get_all_records()
    return [(r['Код'], r['Название файла']) for r in records]

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, (
        "👋 Привет! Я бот SupplyPilot.\n\n"
        "📥 Отправь мне:\n"
        "— Excel файл (BOQ) для перевода и структуры\n"
        "— PDF файл с КП для сравнения с BOQ\n\n"
        "Все таблицы будут добавлены в Google Sheets автоматически."
    ))

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        file_name = message.document.file_name
        ext = file_name.split(".")[-1].lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp_file:
            tmp_file.write(downloaded_file)
            tmp_file_path = tmp_file.name

        if ext in ["xls", "xlsx"]:
            text, df = extract_text_from_excel(tmp_file_path)
            gpt_output = translate_and_structure_boq(text)

            boq_code = get_next_boq_code()
            sheet = client.create(boq_code)
            sheet.share("nzemreli.bot@gmail.com", perm_type='user', role='writer')
            wks = sheet.get_worksheet(0)
            set_with_dataframe(wks, gpt_output)
            register_boq(boq_code, file_name)

            bot.reply_to(message, f"✅ BOQ сохранён как {boq_code} ({file_name})\nhttps://docs.google.com/spreadsheets/d/{sheet.id}")

        elif ext == "pdf":
            text = extract_text_from_pdf(tmp_file_path)
            supplier_name, offer_data = extract_supplier_offer(text)
            pending_pdf[message.chat.id] = (tmp_file_path, supplier_name, offer_data)

            options = get_boq_options()
            if not options:
                bot.reply_to(message, "❌ Нет сохранённых BOQ. Сначала загрузите Excel-файл.")
                return

            msg = "📄 С каким BOQ сравнить это КП?\n\n"
            for i, (code, name) in enumerate(options):
                msg += f"{i+1}. {code} — {name}\n"
            msg += "\nНапишите номер (например, 1):"
            bot.reply_to(message, msg)

        else:
            bot.reply_to(message, "❌ Поддерживаются только Excel и PDF файлы.")

    except Exception as e:
        logging.exception("Error handling document")
        bot.reply_to(message, f"Произошла ошибка: {str(e)}")

@bot.message_handler(func=lambda msg: msg.chat.id in pending_pdf)
def handle_boq_selection(message):
    try:
        index = int(message.text.strip()) - 1
        options = get_boq_options()
        if index < 0 or index >= len(options):
            bot.reply_to(message, "❌ Неверный номер. Попробуйте снова.")
            return

        boq_code = options[index][0]
        boq_sheet = client.open(boq_code)
        sheet = boq_sheet.sheet1
        boq_df = pd.DataFrame(sheet.get_all_records())

        pdf_path, supplier_name, offer_data = pending_pdf.pop(message.chat.id)

        updated_df = update_sheet_with_offer(boq_df, offer_data, supplier_name)
        set_with_dataframe(sheet, updated_df)

        bot.reply_to(message, f"✅ КП от {supplier_name} добавлено в {boq_code}.")

        os.unlink(pdf_path)

    except Exception as e:
        logging.exception("Error in BOQ selection")
        bot.reply_to(message, f"Произошла ошибка при добавлении КП: {str(e)}")

# ======================= Start Bot ============================

if __name__ == "__main__":
    logging.info("🤖 Бот запущен")
    bot.infinity_polling()
