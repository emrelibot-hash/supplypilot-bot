# gpt.py
import openai
import pandas as pd
import re
import os

openai.api_key = os.getenv("OPENAI_API_KEY")


def translate_and_structure_boq(text):
    if not openai.api_key:
        # GPT API not set — fallback: return plain DataFrame
        lines = [line for line in text.splitlines() if line.strip()]
        df = pd.DataFrame({"Description": lines, "Qty": "", "Unit": ""})
        return df

    prompt = f"""
    Преобразуй следующий список позиций в таблицу со столбцами:
    Description | Qty | Unit

    Если строка уже на английском или русском — не переводи. Если на другом языке — переведи на английский.

    Входной текст:
    {text}
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    raw = response["choices"][0]["message"]["content"]
    rows = [re.split(r"\s{2,}|\t", line.strip()) for line in raw.splitlines() if line.strip()]
    df = pd.DataFrame(rows[1:], columns=rows[0]) if len(rows) > 1 else pd.DataFrame()
    return df


def extract_supplier_offer(text):
    if not openai.api_key:
        raise RuntimeError("GPT API ключ не задан для обработки PDF")

    prompt = f"""
    В извлеченном тексте КП найди:
    - Название поставщика (Company Name)
    - Таблицу предложений: Description | Qty | Unit | Unit Price

    Верни результат в виде JSON Python-словаря:
    {
      "supplier": "...",
      "offers": [
        {"description": "...", "qty": ..., "unit": "pcs", "unit_price": ...},
        ...
      ]
    }

    КП:
    {text}
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    parsed = eval(response["choices"][0]["message"]["content"])
    return parsed["supplier"], parsed["offers"]


def update_sheet_with_offer(boq_df, offer_data, supplier):
    unit_col = f"{supplier} Unit Price"
    total_col = f"{supplier} Total"
    notes_col = f"{supplier} Notes"

    boq_df[unit_col] = ""
    boq_df[total_col] = ""
    boq_df[notes_col] = ""

    for i, row in boq_df.iterrows():
        matched = None
        for offer in offer_data:
            if offer["description"][:15].lower() in row["Description"].lower():
                matched = offer
                break

        if matched:
            try:
                boq_qty = float(row["Qty"])
                unit_price = float(matched["unit_price"])
                offer_qty = float(matched["qty"])

                boq_df.at[i, unit_col] = unit_price
                boq_df.at[i, total_col] = unit_price * boq_qty

                if offer_qty != boq_qty:
                    boq_df.at[i, notes_col] = f"offered qty {offer_qty}, required {boq_qty}"
                else:
                    boq_df.at[i, notes_col] = "match"
            except:
                boq_df.at[i, notes_col] = "parse error"
        else:
            boq_df.at[i, notes_col] = "not offered"

    return boq_df
