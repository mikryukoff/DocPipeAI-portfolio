def clean_table(table: list[list[str]]) -> list[list[str]]:
    if not table:
        return []

    cleaned = []

    for row in table:
        if not any(cell and str(cell).strip() for cell in row):
            continue

        cleaned.append([
            str(cell).replace("\n", " ").strip() if cell else ""
            for cell in row
        ])

        cleaned = [list(filter(lambda x: x, row)) for row in cleaned]

    return cleaned
