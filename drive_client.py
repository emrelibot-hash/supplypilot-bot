from __future__ import annotations

import io
import os
import re
from typing import List, Dict, Any, Tuple

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account

# ==== CONFIG ====
SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "credentials.json"

# ВАЖНО: это ID корневой папки Projects (а не папки конкретного проекта)
ROOT_FOLDER_ID = "1J85RsAoGbCAbE8kEtgYRIPLbRcfph1zP"

# ==== CLIENT ====
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=creds)


# ==== DEBUG / DIAGNOSTICS ====
def ping_drive() -> None:
    """Печатает учётку и базовую диагностику корня."""
    about = drive_service.about().get(fields="user(displayName,emailAddress)").execute()
    print(f"[Drive] AUTH as: {about['user']['emailAddress']} ({about['user']['displayName']})")
    try:
        root = drive_service.files().get(fileId=ROOT_FOLDER_ID, fields="id,name").execute()
        print(f"[Drive] ROOT: {root.get('name')} ({root.get('id')})")
    except Exception as e:
        print(f"[ERROR] Cannot access ROOT '{ROOT_FOLDER_ID}': {e}")


# ==== LOW-LEVEL HELPERS ====
def list_folders_in_folder(parent_id: str) -> List[Dict[str, Any]]:
    """Возвращает папки внутри parent_id."""
    results = drive_service.files().list(
        q=f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        pageSize=1000,
        fields="files(id,name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return results.get("files", [])


def list_files_in_folder(folder_id: str) -> List[Dict[str, Any]]:
    """Возвращает файлы (любых типов) внутри folder_id."""
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        pageSize=1000,
        fields="files(id,name,mimeType)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return results.get("files", [])


def download_file(file_id: str) -> bytes:
    """Скачивает файл по ID и возвращает содержимое в bytes."""
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()


def _find_subfolder_by_name(parent_id: str, expected: str) -> Dict[str, Any] | None:
    """Ищет подпапку с именем expected (без учёта регистра и лишних пробелов)."""
    expected_norm = expected.strip().lower()
    for f in list_folders_in_folder(parent_id):
        if f["name"].strip().lower() == expected_norm:
            return f
    return None


# ==== RFQ/BOQ DISCOVERY ====
def find_boq_file(project_folder_id: str) -> Tuple[str | None, bytes | None]:
    """
    Ищем подпапку 'boq' (латиница, строчные). Берём первый файл внутри.
    """
    boq_folder = _find_subfolder_by_name(project_folder_id, "boq")
    if not boq_folder:
        print("[WARN] 'boq' folder not found")
        return None, None

    boq_files = list_files_in_folder(boq_folder["id"])
    if not boq_files:
        print("[WARN] No files in 'boq'")
        return None, None

    boq_file = boq_files[0]
    print(f"[INFO] BOQ file: {boq_file['name']}")
    return boq_file["name"], download_file(boq_file["id"])


def _guess_supplier_from_filename(filename: str) -> str:
    """
    Грубая, но практичная эвристика:
    - берём имя файла без расширения
    - режем по разделителям
    - выпиливаем слова-паразиты (rfq, kp, offer, quotation, quote, price, proposal, комм..., кп)
    - возвращаем первое осмысленное слово (или полный base, если ничего не нашли)
    """
    base = os.path.splitext(filename)[0]
    tokens = re.split(r"[\s._\-]+", base)
    blacklist = {"rfq", "kp", "kz", "offer", "quotation", "quote", "price", "proposal",
                 "коммерческое", "кп", "предложение", "оффер"}
    cleaned = [t for t in tokens if t and t.lower() not in blacklist]
    # Склей 1–2 токена для читаемости, если они есть
    if cleaned:
        # Убираем слишком короткие и числовые хвосты
        cleaned = [t for t in cleaned if not t.isdigit()]
        if cleaned:
            candidate = " ".join(cleaned[:2])
            return candidate.strip()
    return base.strip()


def
