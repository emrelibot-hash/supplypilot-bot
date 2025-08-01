import os
import logging
import json
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Logging
logging.basicConfig(level=logging.INFO)

# Tokens
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

# Init bot
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

# Google Sheets auth
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
