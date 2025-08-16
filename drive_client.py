from __future__ import annotations

import io
from typing import List, Dict, Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account

# ==== CONFIG ====
SCOPES = ["https://www.googleapis.com/auth/drive"]
SERVICE_ACCOUNT_FILE = "credentials.json"

# ВАЖНО: это ID корневой папки Projects (а не папки проекта)
ROOT_FOLDER_ID = "1J85RsAoGbCAbE8kEtgYRIPLbRcfph1zP"

# ==== CLIENT ====
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=creds)


# ==== DEBUG / DIAGNOSTICS ====
def ping_drive() -> None:
    """Печатает учётку, под которой идём в Drive, и детей корня."""
    about = drive_service.about().get(fields="user(displayName,emailAddress)").execute()
    print(
        f"[Drive] AUTH OK as: {about['user']['emailAddress']} "
        f"({about['user']['displayName']})"
    )
    root = drive_service.files().get(
        fileId=ROOT_FOLDER_ID, fields="id,name"
    ).execute()
    print(f"[Drive] ROOT name: {root.get('name')} | id: {root.get('id')}")
    children = list_folders_in_folder(ROOT_FOLDER_ID)
    print(f"[Drive] ROOT child folders: {len(children)} -> {[c['name'] for c in children]}")


# ==== LOW-LEVEL HELPERS ====
def list_folders_in_folder(parent_id: string) -> List[Dict[str, Any]]:
    """Возвращает папки внутри parent_id."""
    results = drive_service.files().list(
        q=f"'{parent_id}' in parents and "
          f"mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        pageSize=1000,
        fields="files(id,name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return results.get("files", [])


def list_files_in_folder(folder_id: string) -> List[Dict[str, Any]]:
    """Возвращает файлы (любых типов) внутри folder_id."""
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        pageSize=1000,
        fields="files(id,name,mimeType)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return results.get("files", [])


def download_file(file_id: string) -> bytes:
    """Скачивает файл по ID и возвращает содержимое в bytes."""
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()


# ==== DOMAIN HELPERS ====
def _find_subfolder_by_name(parent_id: str, expected: str) -> Dict[str, Any] | None:
    """Ищет подпапку с именем expected (регистр/пробелы игнорируются)."""
    expected_norm = expected.strip().lower()
    for f in list_folders_in_folder(parent_id):
        if f["name"].strip().lower() == expected_norm:
            return f
    return None


def find_boq_file(project_folder_id: str) -> tuple[str | None, bytes | None]:
    """
    Ищет подпапку 'boq' (латиница, строчные). Берёт первый файл внутри.
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


def find_offer_files(project_folder_id: str) -> List[Dict[str, Any]]:
    """
    Ищет предложения в подпапке 'кп' (кириллица, строчные).
    Поддерживаем два кейса:
      A) /кп/<Supplier>/*  — подпапки поставщиков
      B) /кп/*             — файлы лежат прямо в 'кп'
    Для надёжности также принимаем латиницу 'kp'.
    """
    kp_folder = (_find_subfolder_by_name(project_folder_id, "кп")
                 or _find_subfolder_by_name(project_folder_id, "kp"))
    if not kp_folder:
        print("[WARN] 'кп' (or 'kp') folder not found")
        return []

    offers: List[Dict[str, Any]] = []

    # A) подпапки поставщиков
    supplier_subfolders = list_folders_in_folder(kp_folder["id"])
    for supplier_folder in supplier_subfolders:
        supplier_name = supplier_folder["name"]
        supplier_files = list_files_in_folder(supplier_folder["id"])
        for f in supplier_files:
            try:
                content = download_file(f["id"])
                offers.append(
                    {"supplier": supplier_name, "filename": f["name"], "bytes": content}
                )
            except Exception as e:
                print(f"[ERROR] download offer '{f['name']}' from '{supplier_name}': {e}")

    # B) файлы прямо в /кп
    top_level_files = list_files_in_folder(kp_folder["id"])
    for f in top_level_files:
        # пропускаем подпапки, здесь только файлы
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        try:
            content = download_file(f["id"])
            offers.append({"supplier": "TOP_LEVEL", "filename": f["name"], "bytes": content})
        except Exception as e:
            print(f"[ERROR] download top-level offer '{f['name']}': {e}")

    print(f"[INFO] Offers found: {len(offers)}")
    return offers


# ==== PUBLIC API ====
def get_projects_from_drive(root_folder_id: str | None = None, *_args, **_kwargs) -> List[Dict[str, Any]]:
    """
    Сканирует проекты в корневой папке и собирает:
      - имя проекта
      - файл BOQ (имя + bytes)
      - список предложений (supplier, filename, bytes)

    Параметры:
      root_folder_id — опционально переопределяет ROOT_FOLDER_ID
      *_args, **_kwargs — «поглощают» лишние аргументы, если функция вызвана как колбэк.

    Возвращает: List[dict]
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

        offers = find_offer_files(pf["id"])
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
