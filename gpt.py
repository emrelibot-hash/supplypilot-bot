import re
import openai
import pandas as pd
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def translate_text(text):
    prompt = f"Translate the following construction-related text to English:\n\n{text}"
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful translator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        print("Translation error:", e)
        return text

def detect_boq_structure(df):
    """
    Automatically detect column names: Description, Qty, Means of Unit
    by scanning top rows and content.
    """
    detected = {
        'Description': None,
        'Qty': None,
        'Means of Unit': None
    }

    unit_triggers = ['pcs', 'piece', 'unit', 'set', 'm2', 'm3', 'sqm', 'cbm', 'шт', 'компл', 'ədəd', 'dona']

    for col in df.columns:
        col_data = df[col].astype(str).head(10).tolist()
        col_joined = " ".join(col_data).lower()

        # Detect Description
        if detected['Description'] is None and any(len(cell.split()) > 3 for cell in col_data):
            detected['Description'] = col
            continue

        # Detect Means of Unit
        if detected['Means of Unit'] is None and any(any(unit in cell.lower() for unit in unit_triggers) for cell in col_data):
            detected['Means of Unit'] = col
            continue

        # Detect Qty
        numeric_ratio = sum(cell.replace('.', '', 1).isdigit() for cell in col_data) / len(col_data)
        if detected['Qty'] is None and numeric_ratio > 0.6:
            detected['Qty'] = col
            continue

    return detected

def translate_and_structure_boq(text):
    try:
        if re.search(r'[а-яА-Яა-ჰא-תא-תا-ي]', text):
            return translate_text(text)
        return text
    except Exception as e:
        print("Translation error fallback:", e)
        return text

def extract_supplier_name_from_pdf(file_bytes):
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_bytes)
        text = ''
        for page in reader.pages[:2]:
            text += page.extract_text() or ''
        # Heuristic: first capitalized phrase that looks like a company name
        match = re.search(r'\b[A-Z][A-Za-z\s,&\-.()]{3,50}\b', text)
        if match:
            return match.group(0).strip()
        return "Unknown Supplier"
    except Exception as e:
        print("PDF name extraction error:", e)
        return "Unknown Supplier"

def compare_offer_with_boq(pdf_text, boq_df):
    # Dummy matching logic for demonstration
    # You will likely replace this with a smarter matching function
    boq_descriptions = boq_df['Description Original'].astype(str).tolist()
    result = []
    for desc in boq_descriptions:
        result.append({
            'BOQ Match': desc,
            'Unit Price': "",  # To be filled with actual matching logic
        })
    return pd.DataFrame(result)
