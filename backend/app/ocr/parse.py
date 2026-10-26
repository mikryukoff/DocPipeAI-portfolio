from loguru import logger
import re


async def parse_table_texts(text: str) -> list:
    try:
        text = (
            text.replace("```markdown", "")
            .replace("```html", "")
            .replace("```", "")
            .replace("text", "")
            .strip()
        )

        if "<table" in text.lower() or "<tr>" in text.lower():
            pattern = r"<t[dh][^>]*>(.*?)<\/t[dh]>"
            raw_matches = re.findall(pattern, text, re.IGNORECASE)

        elif "|" in text:
            pattern = r"\|\s*([^|\n]+?)\s*(?=\||$)"
            raw_matches = re.findall(pattern, text, re.MULTILINE)

        else:
            raw_matches = [line for line in text.split("\n") if line.strip()]

        materials = []
        for match in raw_matches:
            clean_match = re.sub(r"<[^>]+>", "", match).strip()

            if clean_match.lower() == "markdown" or "mapka" in clean_match.lower():
                continue

            if (
                clean_match
                and re.search(r"[A-Za-z]", clean_match)
                and not re.search(r"[А-Яа-яЁё]", clean_match)
            ):

                materials.append(clean_match)

        return materials

    except Exception as e:
        logger.error(f"Ошибка при парсинге таблицы: {e}")
        return []

    
async def parse_diameter(text: str) -> str:
    text = (
            text.replace("```markdown", "")
            .replace("```html", "")
            .replace("```", "")
            .replace("text", "")
            .strip()
        )

    # if "<table" in text.lower() or "<tr>" in text.lower():
    #     pattern = r"<td>Наименование изделия</td>\s*<td>(.*?)</td>"
    # elif "|" in text:
    #     pattern = r"\|\s*На[ий]менование изделия\s*\|\s*(.*?)\s*\|"
    # else:
    #     pattern = r"На[ий]менование изделия\s*:\s*(.*?)\s*"
    pattern = r"На[ий]менование изделия(?:\s*</td>\s*<td>|\s*\|\s*|\s*[\r\n]+\s*)(.*?)(?=\s*</td>|\s*\||\s*[\r\n]|$)"
    
    match = re.search(pattern, text)
    return match.group(1) if match else None