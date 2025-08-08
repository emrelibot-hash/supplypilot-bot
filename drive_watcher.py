from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from config import GOOGLE_FOLDER_ID, GOOGLE_CREDS_JSON

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_ID = GOOGLE_FOLDER_ID

def _svc():
    creds = Credentials.from_service_account_info(GOOGLE_CREDS_JSON, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def list_projects() -> List[dict]:
    """Папки верхнего уровня в корневой папке = проекты."""
    q = f"'{FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = _svc().files().list(q=q, fields="files(id,name)").execute()
    return res.get("files", [])

def _find_subfolder(parent_id: str, name: str) -> str | None:
    q = f"'{parent_id}' in parents and name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = _svc().files().list(q=q, fields="files(id)").execute().get("files", [])
    return res[0]["id"] if res else None

def list_boq_files(project_id: str) -> List[dict]:
    """Все файлы в /boq отсортированы по времени (свежее первым)."""
    boq_id = _find_subfolder(project_id, "boq")
    if not boq_id: return []
    q = f"'{boq_id}' in parents and trashed=false"
    return _svc().files().list(q=q, orderBy="modifiedTime desc",
                               fields="files(id,name,mimeType,modifiedTime)").execute().get("files", [])

def list_kp_files(project_id: str) -> List[Tuple[str, dict]]:
    """[(supplier_name, file_meta)] из подпапок /кп/<Supplier>/"""
    kp_root = _find_subfolder(project_id, "кп")
    if not kp_root: return []
    svc = _svc()
    q = f"'{kp_root}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    suppliers = svc.files().list(q=q, fields="files(id,name)").execute().get("files", [])
    out = []
    for s in suppliers:
        q = f"'{s['id']}' in parents and trashed=false"
        files = svc.files().list(q=q, orderBy="modifiedTime desc",
                                 fields="files(id,name,mimeType,modifiedTime)").execute().get("files", [])
        out += [(s["name"], f) for f in files]
    return out

def download_file_xls_any(file_id: str, out_path: str) -> str:
    """Скачивает файл из Drive как есть (.xls/.xlsx/.csv)"""
    svc = _svc()
    req = svc.files().get_media(fileId=file_id)
    with io.FileIO(out_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            status, done = downloader.next_chunk()
    return out_path
