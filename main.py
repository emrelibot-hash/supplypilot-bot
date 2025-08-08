import os, threading, time
from flask import Flask, jsonify

from drive_watcher import list_projects, list_boq_files, list_kp_files, download_file_xls_any
from sheets_client import ensure_project_sheet, read_boq_current, ensure_supplier_block, write_boq, write_supplier_prices
from processor import parse_boq_xlsx, parse_kp_xlsx, map_kp_to_boq

POLL = int(os.getenv("POLL_SECONDS","60"))

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({"ok": True})

def tick_once():
    projects = list_projects()
    for p in projects:
        project_name, pid = p["name"], p["id"]
        ws = ensure_project_sheet(project_name)

        # 1) BOQ — берём самый свежий файл, если есть
        boq_files = list_boq_files(pid)
        if boq_files:
            fmeta = boq_files[0]
            tmp = f"/tmp/{fmeta['id']}.xls"
            download_file_xls_any(fmeta["id"], tmp)
            rows = parse_boq_xlsx(tmp)
            if rows:
                write_boq(ws, rows)

        # 2) КП — по подпапкам-поставщикам
        kp_items = list_kp_files(pid)
        if kp_items:
            boq_sheet_rows = read_boq_current(ws)  # истина для маппинга
            for supplier, fmeta in kp_items:
                tmp = f"/tmp/{fmeta['id']}.xls"
                download_file_xls_any(fmeta["id"], tmp)
                kp_df = parse_kp_xlsx(tmp)
                ensure_supplier_block(ws, supplier)
                mapped = map_kp_to_boq(boq_sheet_rows, kp_df)
                if mapped:
                    write_supplier_prices(ws, supplier, mapped)

def loop():
    while True:
        try:
            tick_once()
        except Exception as e:
            print("tick error:", repr(e))
        time.sleep(POLL)

if __name__ == "__main__":
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
