import pandas as pd
import re
import PyPDF2
import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def clean_column_name(col):
    if isinstance(col, tuple):
        return " / ".join(str(c) for c in col if pd.notnull(c)).strip()
    if isinstance(col, str):
        return col.strip()
    return str(col)

def find_first_data_row(df):
    for i, row in df.iterrows():
        non_empty = row.dropna()
        if len(non_empty) >= 2 and any(isinstance(v, str) and v.strip() for v in non_empty):
            return i
    return 0

def detect_boq_structure(df: pd.DataFrame):
    start_row = find_first_data_row(df)
    df = df.iloc[start_row:].reset_index(drop=True)

    header_rows = 2 if all(df.iloc[0].notnull()) and all(df.iloc[1].notnull()) else 1
    df.columns = pd.MultiIndex.from_arrays(df.iloc[:header_rows].values) if header_rows == 2 else df.iloc[0].values
    df.columns = [clean_column_name(col) for col in df.columns]
    df = df.iloc[header_rows:].reset_index(drop=True)

    desc_col, qty_col, unit_col = None, None, None

    for col in df.columns:
        col_lc = str(col).lower()
        if any(x in col_lc for x in ["description", "work", "item", "наименование"]):
            desc_col = col
        elif any(x in col_lc for x in ["qty", "quantity", "amount", "რაოდენობა", "кол-во"]):
            qty_col = col
        elif any(x in col_lc for x in ["unit", "measure", "ed.", "ერთეული", "мера"]):
            unit_col = col

    if not qty_col:
        for col in df.columns:
            if pd.to_numeric(df[col], errors='coerce').notnull().sum() > 0:
                qty_col = col
                break

    if not unit_col:
        for col in df.columns:
            if df[col].astype(str).str.lower().str.contains(r"\\b(m2|m3|pcs|set|piece|თვე|ცალი)\\b", regex=True).sum() > 0:
                unit_col = col
                break

    return {
        "df": df,
        "description_column": desc_col,
        "qty_column": qty_col,
        "unit_column": unit_col
    }

def translate_text(text: str, target_language='en') -> str:
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"Translate to {target_language}. Only translated result, nothing else."},
                {"role": "user", "content": text}
            ]
        )
        return response.choices[0].message['content'].strip()
    except Exception as e:
        return text

def extract_supplier_name_from_pdf(pdf_path: str) -> str:
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            first_page = reader.pages[0]
            text = first_page.extract_text()
            match = re.search(r"Supplier[:\s]+(.+?)\n", text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
            else:
                return "Unknown Supplier"
    except Exception as e:
        return "Unknown Supplier"
