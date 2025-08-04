# gpt.py
import openai
import pandas as pd
import re
import os

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
        return ""  # Перевод не требуется
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful translator. Translate the following text to English."},
            {"role": "user", "content": text}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

def translate_and_structure_boq(df: pd.DataFrame):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Попытка найти колонку Description
    description_col = None
    for col in df.columns:
        if "description" in col.lower():
            description_col = col
            break
    if not description_col:
        raise ValueError("Не найдена колонка с описанием (description)")

    # Генерация переведённой колонки
    translated = []
    for val in df[description_col]:
        if not isinstance(val, str):
            translated.append("")
            continue
        lang = detect_language(val)
        if lang in ["russian", "english"]:
            translated.append("")
        else:
            translated.append(translate_text(val))

    df.insert(df.columns.get_loc(description_col) + 1, "Description Translated", translated)
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

def find_best_match(offer_text, boq_df):
    for _, row in boq_df.iterrows():
        desc = row.get("Description", "")
        if isinstance(desc, str) and desc.lower() in offer_text.lower():
            return desc
    return "Not matched"

def extract_supplier_name_from_pdf(text: str):
    # Пытаемся извлечь название компании
    lines = text.splitlines()
    for line in lines:
        if any(keyword in line.lower() for keyword in ["ltd", "llc", "gmbh", "company", "co.", "inc", "group"]):
            return line.strip()
    # fallback
    return lines[0].strip() if lines else "Unknown Supplier"
