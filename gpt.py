# gpt.py
import openai
import pandas as pd
import re
import os
import fitz  # PyMuPDF

openai.api_key = os.getenv("OPENAI_API_KEY")

def detect_language(text):
    if re.search(r'[а-яА-ЯёЁ]', text):
        return "russian"
    if re.search(r'[a-zA-Z]', text):
        return "english"
    return "other"

def translate_text(text):
    lang = detect_language(text)
    if lang in ["russian", "english"]:
        return text  # не переводим

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful translator. Translate the following text to English."},
            {"role": "user", "content": text}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

def translate_and_structure_boq(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    structured_rows = []

    for line in lines:
        translated = translate_text(line)
        structured_rows.append([translated])

    df = pd.DataFrame(structured_rows, columns=["BOQ Item"])
    return df

def extract_supplier_offer(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    offers = []
    for line in lines:
        match = re.search(r'(\d+(?:\.\d+)?)\s*(USD|EUR|GEL)', line, re.IGNORECASE)
        if match:
            offers.append({"raw": line, "price": match.group(1), "currency": match.group(2).upper()})
        else:
            offers.append({"raw": line, "price": None, "currency": None})
    return offers

def find_best_match(offer_text, boq_df):
    for _, row in boq_df.iterrows():
        if row[0].lower() in offer_text.lower():
            return row[0]
    return "Not matched"

def compare_offer_with_boq(text, boq_df):
    offers = extract_supplier_offer(text)
    result = []
    for offer in offers:
        result.append({
            "BOQ Match": find_best_match(offer["raw"], boq_df),
            "Offered Description": offer["raw"],
            "Unit Price": offer["price"],
            "Currency": offer["currency"]
        })
    return pd.DataFrame(result)

def update_sheet_with_offer(worksheet, offer_data):
    existing = worksheet.get_all_values()
    start_row = len(existing) + 2

    worksheet.update(f"A{start_row}", [["Поставщик"]])
    for i, row in enumerate(offer_data):
        values = [
            row.get("BOQ Match", ""),
            row.get("Offered Description", ""),
            row.get("Unit Price", ""),
            row.get("Currency", "")
        ]
        worksheet.update(f"A{start_row + i + 1}", [values])

def extract_supplier_name_from_pdf(pdf_path_or_bytes) -> str:
    """
    Простой способ извлечь имя поставщика из первых строк PDF.
    """
    try:
        if isinstance(pdf_path_or_bytes, bytes):
            doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
        else:
            doc = fitz.open(pdf_path_or_bytes)

        text = ""
        for page in doc:
            text += page.get_text()
            break  # читаем только первую страницу

        lines = text.splitlines()
        for line in lines:
            if any(keyword in line.lower() for keyword in ["supplier", "company", "vendor", "შპს", "ლტდ", "ooo", "llc", "ltd"]):
                return line.strip()
        
        for line in lines:
            if line.strip():
                return line.strip()

        return "Unknown Supplier"
    except Exception:
        return "Unknown Supplier"
