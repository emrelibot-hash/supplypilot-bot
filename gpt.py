### gpt.py

import openai
import os
import re
from typing import List, Dict

openai.api_key = os.getenv("OPENAI_API_KEY")

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

def extract_boq_using_gpt(text: str) -> List[Dict[str, str]]:
    prompt = (
        "You are an assistant that extracts structured BOQ tables from messy text.\n"
        "Return the result as JSON list of dictionaries.\n"
        "Each item must include: Position, Description, Qty, Unit.\n"
        "Example:\n"
        "[\n"
        "  {\"Position\": \"1.1\", \"Description\": \"Air Duct Installation\", \"Qty\": \"25\", \"Unit\": \"m2\"},\n"
        "  {\"Position\": \"1.2\", \"Description\": \"Ventilation Grille\", \"Qty\": \"10\", \"Unit\": \"pcs\"}\n"
        "]"
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            temperature=0,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ]
        )
        content = response.choices[0].message['content']
        data = eval(content)
        return data if isinstance(data, list) else []
    except Exception as e:
        print("GPT error:", e)
        return []

