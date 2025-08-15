import pandas as pd
import io
import mimetypes

def extract_excel_from_bytes(file_bytes, filename=None):
    """Читает Excel из байтов и возвращает DataFrame"""
    extension = None
    if filename:
        extension = filename.split('.')[-1].lower()

    if extension == 'xls' or (not extension and mimetypes.guess_type(filename)[0] == 'application/vnd.ms-excel'):
        return pd.read_excel(io.BytesIO(file_bytes), engine='xlrd')
    else:
        return pd.read_excel(io.BytesIO(file_bytes), engine='openpyxl')
