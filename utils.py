# utils.py
import pandas as pd
import fitz  # PyMuPDF


def extract_text_from_excel(file_path):
    df = pd.read_excel(file_path)
    text = "\n".join(df.iloc[:, 0].astype(str))  # Берём только первый столбец
    return text, df


def extract_text_from_pdf(file_path):
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text
