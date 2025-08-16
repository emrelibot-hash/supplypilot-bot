from __future__ import annotations
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from drive_client import get_projects_from_drive
from processor import parse_boq, parse_rfq, align_offers
from sheets_client import write_project_sheet

if __name__ == "__main__":
    projects = get_projects_from_drive()
    print(f"🟢 Найдено проектов: {len(projects)}")
    for p in projects:
        project_name = p["project_name"]
        print(f"📁 {project_name} | BOQ: {p['boq_file']} | RFQ: {len(p['offers'])}")

        # Парсинг BOQ
        boq_df = parse_boq(p["boq_bytes"])

        # Парсинг RFQ: имя файла -> df
        supplier_to_df = {}
        for off in p["offers"]:
            try:
                df = parse_rfq(off["bytes"])
                supplier_to_df[off["supplier"]] = df
                print(f"   — OK RFQ {off['supplier']}: {off['filename']}")
            except Exception as e:
                print(f"   — FAIL RFQ {off['filename']}: {e}")

        # Сведение и запись в Sheet
        suppliers, table = align_offers(boq_df, supplier_to_df)
        write_project_sheet(project_name, table)
        print(f"   ✅ Sheet updated: {project_name} ({len(suppliers)} suppliers)")
