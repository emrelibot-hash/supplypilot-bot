import os
from typing import List
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from config import GOOGLE_FOLDER_ID, GOOGLE_CREDS_JSON

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_ID = GOOGLE_FOLDER_ID

def _svc():
    creds = Credentials.from_service_account_info(GOOGLE_CREDS_JSON, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def list_projects() -> List[dict]:
    """Возвращает список подпапок (проектов) в корневой папке FOLDER_ID."""
    service = _svc()
    results = service.files().list(
        q=f"'{FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        pageSize=1000,
        fields="files(id, name)"
    ).execute()
    return results.get("files", [])

def list_boq_files(project_id: str) -> List[dict]:
    """Возвращает список BOQ файлов в папке проекта."""
    service = _svc()
    results = service.files().list(
        q=f"'{project_id}' in parents and trashed = false and mimeType contains 'spreadsheet'",
        pageSize=1000,
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get("files", [])

def list_kp_files(project_id: str) -> List[dict]:
    """Возвращает список КП файлов в папке проекта."""
    service = _svc()
    results = service.files().list(
        q=f"'{project_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
        pageSize=1000,
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get("files", [])

def download_file_xls_any(file_id: str, local_path: str):
    """Скачивает XLS/XLSX файл с Google Drive по ID."""
    service = _svc()
    request = service.files().get_media(fileId=file_id)
    with open(local_path, "wb") as f:
        downloader = request.execute()
        f.write(downloader)
