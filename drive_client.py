from __future__ import annotations

import io
import os
import re
from typing import List, Dict, Any, Tuple, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account

# ========= CONFIG =========
SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "credentials.json"

# ВАЖНО: это ID КОРНЕВОЙ папки ПРОЕКТОВ (не одной проектной папки)
ROOT_FOLDER_ID = "1J85RsAoGbCAbE8kEtgYRIPLbRcfph1zP"

# ========= CLIENT =========
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=creds)


# ========= DIAGNOSTICS =========
def ping_drive() -> None:
    """Быстрый sanity-check: учётка и корень."""
    about = drive_service.about().get(fields="user(displayName,emailAddress)").execute()
    print(f"[Drive] AUTH as: {about['user']['emailAddress']} ({about['user']['displayName']})")
    try:
        root = drive_service.files().get(fileId=ROOT_FOLDER_ID, fields="id,name").execute()
        print(f"[Drive] ROOT: {root.get('name')} ({root.get('id')})")
    except Exception as e:
        print(f"[ERROR] Cannot access ROOT '{ROOT_FOLDER_ID}': {e}")


# ========= LOW-LEVEL HELPERS =========
def list_folders_in_folder(parent_id: str) -> List[Dict[str, Any]]:
    """Возвращает папки внутри parent_id."""
    results = drive_service.files().list(
        q=(
            f"'{parent_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        ),
        pageSize=1000,
        fields="files(id,name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return results.get("files", [])


def list_files_in_folder(folder_id: str) -> List[Dict[str, Any]]:
    """Возвращает файлы (любой тип) внутри folder_id."""
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        pageSize=1000,
        fields="files(id,name,mimeType)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return results.get("files", [])


def download_file(file_id: str) -> bytes:
    """Скачивает файл по ID и возвращает bytes."""
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()


def _find_subfolder_by_name(parent_id: str, expected: str) -> Optional[Dict[str, Any]]:
    """Ищет подпапку с точным именем (без учёта регистра/пробелов)."""
    expected_norm = expected.strip().lower()
    for f in list_folders_in_folder(parent_id):
        if f["name"].strip().lower() == expected_norm:
            return f
    return None


# ========= BOQ / RFQ DISCOVERY =========
def find_boq_file(project_folder_id: str) -> Tuple[Optional[str], Optional[bytes]]:
    """
    Ищем подпапку 'boq' (латиница, строчные). Берём первый файл.
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


_SUPPLIER_BLACKLIST = {
    "rfq", "kp", "kz", "offer", "quotation", "quote", "price", "proposal",
    "коммерческое", "кп", "предложение", "оффер"
}


def _guess_supplier_from_filename(filename: str) -> str:
    """
    Эвристика: имя файла -> имя поставщика.
    Берём base name, режем по разделителям, убираем мусорные токены/цифры.
    """
    base = os.path.splitext(filename)[0]
    tokens = re.split(r"[\s._\-]+", base)
    cleaned = [t for t in tokens if t and t.lower() not in _SUPPLIER_BLACKLIST and not t.isdigit()]
    if cleaned:
        return " ".join(cleaned[:2]).strip()
    return base.strip()


def find_rfq_files(project_folder_id: str) -> List[Dict[str, Any]]:
    """
    Ищем предложения в подпапке 'rfq' (без подпапок).
    Fallback для обратной совместимости: 'кп' / 'kp'.
    Поставщик = из имени файла.
    """
    rfq_folder = (
        _find_subfolder_by_name(project_folder_id, "rfq")
        or _find_subfolder_by_name(project_folder_id, "кп")
        or _find_subfolder_by_name(project_folder_id, "kp")
    )
    if not rfq_folder:
        print("[WARN] 'rfq' folder not found (also no 'кп'/'kp')")
        return []

    offers: List[Dict[str, Any]] = []
    files = list_files_in_folder(rfq_folder["id"])
    for f in files:
        # пропускаем подпапки
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        try:
            content = download_file(f["id"])
            supplier = _guess_supplier_from_filename(f["name"])
            offers.append({"supplier": supplier, "filename": f["name"], "bytes": content})
        except Exception as e:
            print(f"[ERROR] download RFQ '{f['name']}': {e}")

    print(f"[INFO] RFQ files found: {len(offers)}")
    return offers


# ========= PUBLIC API =========
def get_projects_from_drive(root_folder_id: Optional[str] = None, *_args, **_kwargs) -> List[Dict[str, Any]]:
    """
    Сканирует проекты в корневой папке и возвращает список:
      {
        "project_name": str,
        "boq_file": str | None,
        "boq_bytes": bytes | None,
        "offers": List[{"supplier": str, "filename": str, "bytes": bytes}]
      }

    Параметры:
      - root_folder_id: опционально переопределяет ROOT_FOLDER_ID
      - *_args, **_kwargs: безопасно «проглатывают» лишние аргументы, если функция используется как колбэк
    """
    folder_id = root_folder_id or ROOT_FOLDER_ID
    projects: List[Dict[str, Any]] = []

    # Диагностика корня
    try:
        root = drive_service.files().get(fileId=folder_id, fields="id,name").execute()
        print(f"[INFO] Scanning ROOT: {root.get('name')} ({root.get('id')})")
    except Exception as e:
        print(f"[ERROR] Cannot access ROOT '{folder_id}': {e}")
        return projects

    project_folders = list_folders_in_folder(folder_id)
    print(f"[INFO] Project folders discovered: {len(project_folders)}")

    for pf in project_folders:
        print(f"[INFO] Project: {pf['name']} ({pf['id']})")
        boq_name, boq_bytes = find_boq_file(pf["id"])
        if not boq_bytes:
            print("[WARN] Skip project — BOQ missing")
            continue

        offers = find_rfq_files(pf["id"])
        projects.append(
            {
                "project_name": pf["name"],
                "boq_file": boq_name,
                "boq_bytes": boq_bytes,
                "offers": offers,
            }
        )

    print(f"[INFO] Total projects ready: {len(projects)}")
    return projects
