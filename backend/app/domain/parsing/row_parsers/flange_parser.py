import re

from backend.app.domain.models.specification import Flange
from .base import SpecRowParser


class FlangeRowParser(SpecRowParser):

    def parse(self, line: list[str]):
        if not line[0].isdigit():
            return None

        position = int(line[0])
        name = " ".join(line[1:-2]).strip()
        unit = line[-2]
        quantity = float(line[-1].replace(",", "."))

        flange = Flange(position, name, unit, quantity)
        
        # Извлекаем DN и PN из имени
        dn_match = re.search(r'DN\s?(\d+)', name, re.IGNORECASE)
        if dn_match:
            flange.dn = dn_match.group(1)
        else:
            flange.dn = ""
        
        pn_match = re.search(r'PN\s?(\d+)', name, re.IGNORECASE)
        if pn_match:
            pn = int(pn_match.group(1))
            flange.pn = f"{str(pn / 10).replace(".", ",")} ({pn})"
        else:
            flange.pn = ""
        
        # Извлекаем марку стали (steel_grade) - ищем "EN 1." с цифрами и точками
        steel_match = re.search(r'EN\s+1\.\d+', name)
        if steel_match:
            flange.steel_grade = steel_match.group(0)
        else:
            flange.steel_grade = ""
        
        # Извлекаем стандарт фланца (flange_gost) - ищем "EN" с цифрами и тире
        # Пример: EN 1092-1
        flange_gost_match = re.search(r'EN\s+\d+-\d+', name)
        if flange_gost_match:
            flange.flange_gost = flange_gost_match.group(0)
        else:
            flange.flange_gost = ""

        # Извлекаем данные по крепежу только из части после "В комплекте:"
        # Принцип как у steel_grade/flange_gost, но с доп. нормализацией EN для материала.
        kit_match = re.search(r'в\s+комплекте\s*:\s*(.+)', name, re.IGNORECASE | re.DOTALL)
        if kit_match:
            kit_text = kit_match.group(1)

            # Ищем первый материал после слова "материал"
            # Примеры: "материал 1.4462 ..." и "материал EN 1.4462 ..."
            bolt_grade_match = re.search(
                r'материал\s*:?\s*(EN\s+)?([0-9]+(?:\.[0-9]+)+)',
                kit_text,
                re.IGNORECASE,
            )
            if bolt_grade_match:
                raw_grade = bolt_grade_match.group(2)
                flange.bolt_grade = f"EN {raw_grade}"
            else:
                flange.bolt_grade = ""

            # Ищем первый стандарт вида "по EN 10217-7"
            bolt_gost_match = re.search(r'по\s+(EN\s+\d+-\d+)', kit_text, re.IGNORECASE)
            if bolt_gost_match:
                flange.bolt_gost = bolt_gost_match.group(1).upper()
            else:
                flange.bolt_gost = ""
        else:
            flange.bolt_grade = ""
            flange.bolt_gost = ""
        
        # Форматируем имя (оставляем только первую часть до запятой)
        # Но сохраняем DN и PN, если они есть
        name_parts = name.split(",")
        base_name = name_parts[0].strip() if name_parts else name
        
        # Если в base_name есть DN и PN, оставляем как есть, иначе добавляем из полного имени
        if flange.dn or flange.pn:
            # Собираем имя с DN/PN
            new_name = base_name
            if flange.dn and f"DN{flange.dn}" not in new_name:
                new_name += f" DN{flange.dn}"
            if flange.pn and f"PN{pn}" not in new_name:
                new_name += f" PN{pn}"
            flange.name = new_name
        else:
            flange.name = base_name

        return flange