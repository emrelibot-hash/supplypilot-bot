# === main.py ===
import os
import telebot
import pandas as pd
import tempfile
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from gpt import extract_boq_using_gpt, translate_text

# === CONFIG ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

SPREADSHEET_ID = "1zKd3hq7R-CI_i0azdZsdIPihBNT-6BlhADW0M0eiGpo"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = "credentials.json"
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
sheet = build('sheets', 'v4', credentials=creds).spreadsheets()

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
    body = {
        "requests": [{
            "addSheet": {
                "properties": {"title": project_name[:100]}
            }
        }]
    }
    try:
        sheet.batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
    except Exception as e:
        print("Sheet creation error:", e)


def write_boq_to_sheet(project_name, df):
    values = [df.columns.tolist()] + df.values.tolist()
    sheet.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{project_name}'!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

# === BOT HANDLERS ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет! Отправь мне Excel-файл BOQ (.xlsx), и я добавлю его в таблицу.")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
        f.write(downloaded)
        temp_path = f.name

    try:
        project_name = os.path.splitext(message.document.file_name)[0]
        xls = pd.ExcelFile(temp_path)
        combined_df = pd.DataFrame()

        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name)
            if df.empty:
                continue

            extracted = extract_boq_using_gpt(df)
            if not extracted.empty:
                combined_df = pd.concat([combined_df, extracted], ignore_index=True)

        if combined_df.empty:
            bot.reply_to(message, "❌ Не удалось извлечь позиции из таблицы. Возможно, формат не поддерживается.")
            return

        add_project_to_registry(project_name)
        create_project_sheet(project_name)
        write_boq_to_sheet(project_name, combined_df)
        bot.reply_to(message, f"✅ Проект '{project_name}' успешно добавлен!")

    except Exception as e:
        print("Ошибка обработки документа:", e)
        bot.reply_to(message, "⚠️ Ошибка при обработке файла.")

bot.infinity_polling()
