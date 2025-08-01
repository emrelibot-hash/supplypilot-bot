    elif text.lower().startswith("создать rfq"):
        # Извлекаем название проекта
        project_name = text[len("создать rfq"):].strip()
        # Получаем текущее количество листов
        meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        existing = [s["properties"]["title"] for s in meta["sheets"] if s["properties"]["title"].startswith("RFQ-")]
        next_num = len(existing) + 1
        new_title = f"RFQ-{next_num}"

        # Создаём новый лист
        batch = {
            "requests": [
                {"addSheet": {"properties": {"title": new_title}}}
            ]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID, body=batch
        ).execute()

        # Записываем заголовки в новую вкладку
        headers = [["Поставщик", "Цена USD", "Условия", "Комментарий"]]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{new_title}'!A1",
            valueInputOption="RAW",
            body={"values": headers}
        ).execute()

        # Формируем ссылку на лист
        sheet_id = [s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == new_title][0]
        link = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={sheet_id}"

        send_message(chat_id, f"✔ Лист {new_title} для “{project_name}” создан: {link}")
