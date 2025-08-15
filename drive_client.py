# drive_client.py
import os
import mimetypes
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

creds = service_account.Credentials.from_service_account_info(
    eval(GOOGLE_CREDS_JSON), scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=creds)

class ProjectFolder:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.boq_path = None
        self.boq_written = False
        self.offer_files = []  # List of OfferFile instances

    def mark_boq_as_written(self):
        self.boq_written = True

    def unprocessed_offers(self):
        return [offer for offer in self.offer_files if not offer.processed]

class OfferFile:
    def __init__(self, file_path, supplier_name):
        self.file_path = file_path
        self.supplier_name = supplier_name
        self.processed = False

    def mark_as_processed(self):
        self.processed = True

def list_folders(parent_id):
    results = drive_service.files().list(
        q=f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id, name)",
    ).execute()
    return results.get("files", [])

def list_files(parent_id):
    results = drive_service.files().list(
        q=f"'{parent_id}' in parents and trashed = false",
        fields="files(id, name, mimeType)",
    ).execute()
    return results.get("files", [])

def download_file(file_id, filename):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.FileIO(filename, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return filename

def get_projects_from_drive(root_folder_id):
    projects = []

    for project_meta in list_folders(root_folder_id):
        project = ProjectFolder(project_meta["id"], project_meta["name"])
        subfolders = list_folders(project.id)

        for sub in subfolders:
            sub_name = sub["name"].lower()

            if "boq" in sub_name:
                files = list_files(sub["id"])
                for file in files:
                    if file["name"].endswith((".xls", ".xlsx")):
                        local_path = f"/tmp/{file['name']}"
                        download_file(file["id"], local_path)
                        project.boq_path = local_path

            elif "кп" in sub_name or "kp" in sub_name:
                supplier_folders = list_folders(sub["id"])
                for supplier in supplier_folders:
                    supplier_name = supplier["name"]
                    offer_files = list_files(supplier["id"])
                    for file in offer_files:
                        if file["name"].endswith((".xls", ".xlsx", ".pdf")):
                            local_path = f"/tmp/{file['name']}"
                            download_file(file["id"], local_path)
                            project.offer_files.append(OfferFile(local_path, supplier_name))

        projects.append(project)

    return projects
