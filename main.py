# main.py
import os
import time
from drive_client import get_projects_from_drive
from sheets_client import write_boq_to_sheet, write_offer_to_sheet
from gpt import extract_boq_using_gpt, extract_offer_using_gpt

POLL_SECONDS = int(os.getenv("POLL_SECONDS", 60))
GOOGLE_FOLDER_ID = os.getenv("GOOGLE_FOLDER_ID")

def process_all_projects():
    projects = get_projects_from_drive(GOOGLE_FOLDER_ID)
    for project in projects:
        if project.boq_path and not project.boq_written:
            boq_data = extract_boq_using_gpt(project.boq_path)
            write_boq_to_sheet(project.name, boq_data)
            project.mark_boq_as_written()

        for offer in project.unprocessed_offers():
            offer_data = extract_offer_using_gpt(offer.file_path, offer.supplier_name)
            write_offer_to_sheet(project.name, offer_data)
            offer.mark_as_processed()

if __name__ == "__main__":
    print("[System] SupplyPilot started. Monitoring Drive...")
    while True:
        try:
            process_all_projects()
        except Exception as e:
            print(f"[Error] {e}")
        time.sleep(POLL_SECONDS)
