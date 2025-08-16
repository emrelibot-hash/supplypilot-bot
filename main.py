import os
import sys

# Страхуем PYTHONPATH на Render (где код находится в /opt/render/project/src)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from drive_client import get_projects_from_drive

if __name__ == "__main__":
    projects = get_projects_from_drive()  # можно передать root_id, если нужно: get_projects_from_drive("...")
    print(f"🟢 Найдено проектов: {len(projects)}")
    for p in projects:
        project_name = p.get("project_name", "<no name>")
        boq_name = p.get("boq_file") or "<no BOQ>"
        offers = p.get("offers", [])
        print(f"📁 {project_name} | BOQ: {boq_name} | RFQ: {len(offers)}")
        for off in offers:
            print(f"   — {off.get('supplier','<supplier>')}: {off.get('filename','<file>')}")
