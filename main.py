import threading
import time
from flask import Flask, jsonify

from config import POLL_SECONDS
from drive_watcher import (
    list_projects,
    list_boq_files,
    list_kp_files,
    download_file_xls_any,
)
from sheets_client import (
    ensure_project_sheet,
    read_boq_current,
    ensure_supplier_block,
    write_boq,
    write_supplier_prices,
)
from processor import parse_boq_xlsx, parse_kp_xlsx, map_kp_to_boq

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({"ok": True})

def tick_once():
    """Один цикл: пройтись по всем проектам, обновить BOQ и КП."""
    projects = list_projects()
    for p in projects:
        project_name, pid = p["name"], p["id"]
        ws = ensure_project_sheet(project_name)

        # 1) BOQ — берём самый свежий файл из /boq (если есть)
        boq_files = list_boq_files(pid)
        if boq_files:
            fmeta = boq_files[0]
            tmp = f"/tmp/{fmeta['id']}.xls"  # поддержка .xls/.xlsx — парсер сам разрулит
            download_file_xls_any(fmeta["id"], tmp)
            rows = parse_boq_xlsx(tmp)
            if rows:
                write_boq(ws, rows)

        # 2) КП — из подпапок /кп/<Supplier>/
        kp_items = list_kp_files(pid)
        if kp_items:
            # читаем актуальный BOQ прямо из листа, чтобы маппить корректно
            boq_sheet_rows = read_boq_current(ws)
            for supplier, fmeta in kp_items:
                tmp = f"/tmp/{fmeta['id']}.xls"
                download_file_xls_any(fmeta["id"], tmp)
                kp_df = parse_kp_xlsx(tmp)

                # Блок поставщика создаём динамически при первом КП
                ensure_supplier_block(ws, supplier)

                # Маппинг КП → строки BOQ в листе. Цену пишем всегда.
                mapped = map_kp_to_boq(boq_sheet_rows, kp_df)
                if mapped:
                    write_supplier_prices(ws, supplier, mapped)

def loop():
    while True:
        try:
            tick_once()
        except Exception as e:
            # Лог в stdout для Render
            print("tick error:", repr(e))
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    # Фоновый воркер
    t = threading.Thread(target=loop, daemon=True)
    t.start()

    # HTTP, чтобы Render держал сервис живым
    app.run(host="0.0.0.0", port=int(__import__("os").getenv("PORT", 8080)))
