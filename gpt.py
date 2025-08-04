import pandas as pd
import re
import PyPDF2
import openai
import os
import json

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

def detect_boq_structure_with_gpt(df: pd.DataFrame):
    content_preview = df.head(20).to_csv(index=False)
    prompt = f"""
You are a procurement assistant. Below is a table extracted from an Excel BOQ file. Your job is to determine which columns represent:
- Description (name of the item)
- Quantity (number of units required)
- Unit (unit of measure like pcs, m2, etc.)

Output a JSON object like:
{{
    "description_column": "ColumnName",
    "qty_column": "ColumnName",
    "unit_column": "ColumnName"
}}

Table:
{content_preview}
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        content = response.choices[0].message['content']
        parsed = json.loads(content)
        return {
            "df": df,
            "description_column": parsed.get("description_column"),
            "qty_column": parsed.get("qty_column"),
            "unit_column": parsed.get("unit_column")
        }
    except Exception as e:
        print("GPT structuring failed:", e)
        return {"df": df, "description_column": None, "qty_column": None, "unit_column": None}

def translate_text(text: str, target_language='en') -> str:
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
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
