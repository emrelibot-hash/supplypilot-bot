# gpt.py

import openai
import os
import pandas as pd
import pdfplumber

openai.api_key = os.getenv("OPENAI_API_KEY")

def call_gpt(prompt: str, model="gpt-3.5-turbo", max_tokens=1500):
    response = openai.ChatCompletion.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant for parsing tables and matching procurement data."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=max_tokens
    )
    return response.choices[0].message.content.strip()

def extract_text_from_excel(file_path: str) -> str:
    try:
        df_list = pd.read_excel(file_path, sheet_name=None)
        text_chunks = []
        for sheet_name, df in df_list.items():
            df = df.fillna("")
            text = "\n".join(["\t".join(map(str, row)) for row in df.values])
            text_chunks.append(f"[{sheet_name}]\n{text}")
        return "\n\n".join(text_chunks)
    except Exception as e:
        return f"[Error reading Excel file: {e}]"

def extract_text_from_pdf(file_path: str) -> str:
    try:
        with pdfplumber.open(file_path) as pdf:
            pages = [page.extract_text() for page in pdf.pages if page.extract_text()]
            return "\n\n".join(pages)
    except Exception as e:
        return f"[Error reading PDF file: {e}]"

def extract_boq_using_gpt(file_path: str) -> list:
    print(f"[GPT] Extracting BOQ from {file_path}")
    if file_path.lower().endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_path)
    else:
        raw_text = extract_text_from_excel(file_path)

    prompt = f"""
You are given the raw contents of a BOQ (Bill of Quantities). Extract a clean structured list in the format:
No | Description | Unit | Qty

If section headers are used, include them as rows with only the Description field filled (other fields empty).

Respond with the result as JSON array of objects with keys:
- number (or null if not applicable),
- description,
- unit,
- qty

Here is the BOQ content:
