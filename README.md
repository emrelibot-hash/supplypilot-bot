# Supplypilot Drive → Sheets (MVP)

**Что делает:**
- Читает новые проекты (папки) в Google Drive (по `GOOGLE_FOLDER_ID`).
- Для каждой папки `<PROJECT_NAME>`:
  - `/boq/*` → парсит BOQ (.xls/.xlsx), пишет в мастер-таблицу (`GOOGLE_SHEET_ID`) на лист `<PROJECT_NAME>`: `No|Description|Unit|Qty|Notes (System)`.
  - `/кп/<Supplier>/*` → парсит КП (.xls/.xlsx), добавляет блок `<Supplier> — Unit Price|Total|Match|Notes`, **всегда** пишет цену, `Total=UnitPrice×Qty(BOQ)`, расхождения в Match/Notes.

**Запуск локально**
1. Создай `.env` на основе `.env.example` (вставь JSON сервис-аккаунта одной строкой).
2. `pip install -r requirements.txt`
3. `python main.py`
4. Проверь `http://localhost:8080/health`

**Деплой на Render**
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`
- Env Vars: `GOOGLE_SHEET_ID`, `GOOGLE_FOLDER_ID`, `GOOGLE_CREDS_JSON`, `POLL_SECONDS`, `DECIMAL_LOCALE`

**Структура в Drive**
