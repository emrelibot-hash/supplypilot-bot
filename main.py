# main.py

import os
import telebot
import fitz
import tempfile
import openai
import gspread
import pandas as pd
from gspread_dataframe import set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials
from gpt import translate_and_structure_boq, compare_offer_with_boq
from datetime import datetime

# Переменные из окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
TEMPLATE_FILE_ID = GOOGLE_SHEET_ID  # ID шаблона
REGISTRY_SHEET_NAME = "Registry"

# Настройки OpenAI
openai.api_key = OPENAI_API_KEY

# Авторизация в Google
import json
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(credentials)

# Инициализация Telegram-бота
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Создание копии шаблона
def copy_template(title):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaInMemoryUpload
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    drive_service = build('drive', 'v3', credentials=creds)

    copied_file = {'name': title}
    copied = drive_service.files().copy(fileId=TEMPLATE_FILE_ID, body=copied_file).execute()
    return copied['id']

# Работа с реестром
def ensure_registry(spreadsheet):
    try:
        return spreadsheet.worksheet(REGISTRY_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=REGISTRY_SHEET_NAME, rows="100", cols="3")

def get_next_boq_code():
    registry_sheet = ensure_registry(gc.open_by_key(GOOGLE_SHEET_ID))
    existing = registry_sheet.get_all_values()
    count = len(existing)
    code = f"BOQ-{count+1:03d}"
    registry_sheet.update(f"A{count+1}", [[code, str(datetime.now())]])
    return code

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, "👋 Привет! Отправь мне:\n— Excel файл (BOQ) для перевода и структуры\n— PDF файл с КП для сравнения с BOQ")

boq_df_cache = {}

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        file_path = file_info.file_path
        downloaded = bot.download_file(file_path)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(downloaded)
            tmp_path = tmp.name

        filename = message.document.file_name.lower()
        boq_code = get_next_boq_code()
        sheet_id = copy_template(boq_code)
        spreadsheet = gc.open_by_key(sheet_id)
        sheet = spreadsheet.sheet1

        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            df = pd.read_excel(tmp_path)
            text = '\n'.join(str(row) for row in df.iloc[:, 0].tolist())
            boq_df = translate_and_structure_boq(text)
            boq_df_cache[message.chat.id] = boq_df

            sheet.update("A1", [["BOQ Item"]])
            set_with_dataframe(sheet, boq_df, row=2, col=1)

            # Обновляем статус в реестре
            registry = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(REGISTRY_SHEET_NAME)
            registry.append_row([boq_code, f"https://docs.google.com/spreadsheets/d/{sheet_id}", "🟡 RFQ stage"])
            bot.reply_to(message, f"📄 BOQ добавлен в Google Sheet: https://docs.google.com/spreadsheets/d/{sheet_id}")

        elif filename.endswith('.pdf'):
            text = extract_text_from_pdf(tmp_path)
            boq_df = boq_df_cache.get(message.chat.id)
            if boq_df is None:
                bot.reply_to(message, "❗ Сначала отправьте BOQ Excel файл.")
                return

            offer_df = compare_offer_with_boq(text, boq_df)
            supplier_name = f"Supplier {datetime.now().strftime('%H:%M:%S')}"
            insert_supplier_offer(sheet, offer_df, supplier_name, boq_df)
            bot.reply_to(message, f"✅ КП от {supplier_name} добавлено к BOQ.")

    except Exception as e:
        print(e)
        bot.reply_to(message, f"Произошла ошибка: {e}")

def extract_text_from_pdf(path):
    doc = fitz.open(path)
    text = ''
    for page in doc:
        text += page.get_text()
    return text

def insert_supplier_offer(sheet, df, supplier, boq_df):
    values = sheet.get_all_values()
    header = values[0]
    qty_list = [1] * len(boq_df)  # Default qty

    if 'Qty' in boq_df.columns:
        qty_list = boq_df['Qty'].astype(float).tolist()

    base_col = len(header) + 1
    sheet.update_cell(1, base_col, f"{supplier}")
    sheet.update_cell(2, base_col, "Unit Price")
    sheet.update_cell(2, base_col + 1, "Total Price")
    sheet.update_cell(2, base_col + 2, "Notes")

    for i, row in df.iterrows():
        boq_item = row["BOQ Match"]
        price = row["Unit Price"]
        currency = row["Currency"]
        note = ""

        qty = 1
        for j, item_row in boq_df.iterrows():
            if item_row[0] == boq_item:
                qty = qty_list[j]
                break

        if boq_item == "Not matched":
            note = "❗ Item not matched"
        elif row["Offered Description"].lower() != boq_item.lower():
            note = "❗ Description differs"
        if price is None:
            unit = ""
            total = ""
        else:
            unit = f"{price} {currency}"
            total_val = round(float(price) * float(qty), 2)
            total = f"{total_val} {currency}"

        sheet.update_cell(i + 3, base_col, unit)
        sheet.update_cell(i + 3, base_col + 1, total)
        sheet.update_cell(i + 3, base_col + 2, note)

# Запуск
if __name__ == '__main__':
    print("🤖 Bot is running...")
    bot.infinity_polling()
