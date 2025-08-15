# SupplyPilot: Google Drive → Google Sheets

## Что делает:
- Следит за папкой в Google Drive (`GOOGLE_FOLDER_ID`)
- В каждой подпапке проекта ищет:
  - `/boq/` — содержит один BOQ-файл (.xls/.xlsx)
  - `/кп/<Supplier>/` — папки поставщиков с их КП-файлами (.xls/.xlsx)
- BOQ парсится и переносится в Google Sheets (`GOOGLE_SHEET_ID`) на отдельный лист (по имени проекта)
- КП каждого поставщика сравниваются с BOQ и добавляются в ту же таблицу (с колонками `Unit Price | Total | Match | Notes`)

## Формат таблицы:

