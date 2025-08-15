import openai
import os
import pandas as pd
import PyPDF2

openai.api_key = os.getenv("OPENAI_API_KEY")

def extract_boq_using_gpt(file_path: str):
    df = pd.read_excel(file_path, dtype=str).fillna("")
    text = df.to_string(index=False, header=False)

    prompt = f"""
You are a tender analyst. From the following table text, extract structured BOQ data.

Return ONLY a JSON array of objects with:
- no (line/item number)
- description (work description)
- unit (unit of measure)
- qty (quantity)

Example:
[
  {{"no": "1", "description": "Installation of ventilation", "unit": "m2", "qty": "120"}},
  ...
]

TABLE:
{text}
    """

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an expert in construction tenders."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
    )

    result = response.choices[0].message.content
    try:
        items = eval(result)
        rows = [[i["no"], i["description"], i["unit"], i["qty"], ""] for i in items]
        return rows
    except Exception as e:
        print("[GPT Parse Error] BOQ:", e)
        return []

def extract_text_from_pdf(file_path: str) -> str:
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            pages_text = [page.extract_text() for page in reader.pages]
            return "\n".join(pages_text)
    except Exception as e:
        print(f"[PDF Read Error] {e}")
        return ""

def extract_offer_using_gpt(file_path: str, supplier: str):
    text = ""

    if file_path.lower().endswith(".pdf"):
        text = extract_text_from_pdf(file_path)
    elif file_path.lower().endswith((".xls", ".xlsx")):
        df = pd.read_excel(file_path, dtype=str).fillna("")
        text = df.to_string(index=False, header=False)
    else:
        print(f"[Unsupported File] {file_path}")
        return []

    prompt = f"""
You are analyzing a supplier offer. Extract item prices and match them to BOQ.

Return ONLY a JSON list of:
[
  {{
    "no": "1",
    "unit_price": "12.50",
    "total": "1250",
    "match": "✅" or "❗",
    "notes": "text if needed"
  }},
  ...
]
Assume BOQ quantity is known. Always return unit_price and compute total = unit_price * qty.

TABLE:
{text}
    """

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a procurement analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
    )

    result = response.choices[0].message.content
    try:
        items = eval(result)
        rows = [[i["unit_price"], i["total"], i["match"], i["notes"]] for i in items]
        return [{"supplier": supplier, "rows": rows}]
    except Exception as e:
        print("[GPT Parse Error] Offer:", e)
        return []
