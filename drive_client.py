from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
import io
import os
import mimetypes
import pandas as pd
from utils import extract_excel_from_bytes

# Константы
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'credentials.json'
ROOT_FOLDER_ID = '1J85RsAoGbCAbE8kEtgYRIPLbRcfph1zP'  # ← заменить при необходимости

# Инициализация клиента
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

def list_folders_in_folder(parent_id):
    """Возвращает список папок внутри указанной папки"""
    results = drive_service.files().list(
        q=f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        pageSize=1000,
        fields="files(id, name)").execute()
    return results.get('files', [])

def list_files_in_folder(folder_id):
    """Возвращает список файлов (не папок) внутри указанной папки"""
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        pageSize=1000,
        fields="files(id, name, mimeType)").execute()
    return results.get('files', [])

def download_file(file_id):
    """Скачивает файл и возвращает байты"""
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()

def find_boq_file(project_folder_id):
    """Ищет BOQ-файл в подпапке /boq/"""
    subfolders = list_folders_in_folder(project_folder_id)
    boq_folder = next((f for f in subfolders if f['name'].lower() == 'boq'), None)
    if not boq_folder:
        return None, None
    boq_files = list_files_in_folder(boq_folder['id'])
    if not boq_files:
        return None, None
    boq_file = boq_files[0]
    boq_bytes = download_file(boq_file['id'])
    return boq_file['name'], boq_bytes

def find_offer_files(project_folder_id):
    """Ищет все предложения в подпапке /кп/<Поставщик>/"""
    supplier_folders = list_folders_in_folder(project_folder_id)
    offers = []

    for folder in supplier_folders:
        if folder['name'].lower() != 'кп':
            continue
        supplier_subfolders = list_folders_in_folder(folder['id'])
        for supplier_folder in supplier_subfolders:
            supplier_name = supplier_folder['name']
            supplier_files = list_files_in_folder(supplier_folder['id'])
            for file in supplier_files:
                file_bytes = download_file(file['id'])
                offers.append({
                    'supplier': supplier_name,
                    'filename': file['name'],
                    'bytes': file_bytes
                })
    return offers

def get_projects_from_drive():
    """Сканирует все проекты в корневой папке и собирает BOQ + КП"""
    projects = []
    folders = list_folders_in_folder(ROOT_FOLDER_ID)
    for folder in folders:
        boq_name, boq_bytes = find_boq_file(folder['id'])
        if not boq_bytes:
            continue
        offers = find_offer_files(folder['id'])
        projects.append({
            'project_name': folder['name'],
            'boq_file': boq_name,
            'boq_bytes': boq_bytes,
            'offers': offers
        })
    return projects
