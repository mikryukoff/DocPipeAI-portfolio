from .placeholders import replace_placeholder_in_cell_bold
from .table_formatting import format_table


def fill_sections_table(doc, pipeline):
    """
    Логика из _fill_sections_table: ищем таблицу с [TABLE_SECTIONS]
    очищаем, заполняем pipeline.pipelines_len
    """
    target_table = None
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if "[TABLE_SECTIONS]" in cell.text:
                    target_table = table
                    replace_placeholder_in_cell_bold(cell, "[TABLE_SECTIONS]", "№ п/п")
                    break
            if target_table:
                break
        if target_table:
            break

    if not target_table:
        return False

    # удаляем, оставляя заголовок
    while len(target_table.rows) > 1:
        target_table._tbl.remove(target_table.rows[1]._tr)

    if hasattr(pipeline, 'pipelines_len') and pipeline.pipelines_len:
        for i, (dimension, data) in enumerate(pipeline.pipelines_len.items(), 1):
            if i > len(target_table.rows) - 1:
                target_table.add_row()
            row = target_table.rows[i]
            if len(row.cells) >= 4:
                row.cells[0].text = str(i)
                row.cells[1].text = "\n".join([f"Схема сварных соединений №{page}" for page in data.pages])
                row.cells[2].text = dimension
                row.cells[3].text = str(data.total_length)

        format_table(target_table)
    return True
