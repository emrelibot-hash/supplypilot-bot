import os
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

# Загружаем ключи
SERVICE_ACCOUNT_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Инициализация клиента Google Drive
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=credentials)

# ID корневой папки с проектами
ROOT_FOLDER_ID = os.getenv("GOOGLE_FOLDER_ID")

def list_folders_in_folder(folder_id):
    """Возвращает список подпапок внутри указанной папки."""
    try:
        query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])
    except HttpError as error:
        print(f"Ошибка при получении списка папок: {error}")
        return []

def list_files_in_folder(folder_id):
    """Возвращает список файлов внутри указанной папки."""
    try:
        query = f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])
    except HttpError as error:
        print(f"Ошибка при получении списка файлов: {error}")
        return []

def get_projects_from_drive():
    """
    Сканирует корневую папку и собирает:
    - BOQ файл
    - список RFQ файлов (каждый = поставщик)
    """
    projects = []

    project_folders = list_folders_in_folder(ROOT_FOLDER_ID)
    for project in project_folders:
        project_id = project["id"]
        project_name = project["name"]

        # Ищем подпапки boq и rfq
        subfolders = list_folders_in_folder(project_id)
        boq_file = None
        rfq_files = []

        for sf in subfolders:
            if sf["name"].lower() == "boq":
                boq_files = list_files_in_folder(sf["id"])
                if boq_files:
                    boq_file = boq_files[0]  # берем только один файл
            elif sf["name"].lower() == "rfq":
                rfq_files = list_files_in_folder(sf["id"])  # список файлов

        if boq_file and rfq_files:
            projects.append({
                "name": project_name,
                "boq": boq_file,
                "rfqs": rfq_files
            })

    return projects
