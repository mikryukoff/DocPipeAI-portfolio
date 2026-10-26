import re
from dataclasses import dataclass

from backend.app.domain.parsing.armature_gost_store import get_armature_gost_store
from backend.app.domain.parsing.armature_text import (
    bilingual_head_before_dn,
    extract_russian_base_name,
)


@dataclass
class ArmatureExcelUpdate:
    source_prefix: str
    normalized_name: str
    dn: str
    pn: str
    material_grade: str
    gost: str
    source_raw: str


class ExcelSpecaArmatureParser:
    @staticmethod
    def _format_pn_for_storage(pn_raw: str) -> str:
        raw = (pn_raw or "").strip()
        value = raw.replace(",", ".")
        if not value:
            return ""
        try:
            num = float(value)
        except ValueError:
            return pn_raw
        if num <= 0:
            return pn_raw
        if "." in value:
            mpa_num = num
            bar = int(round(num * 10))
        else:
            bar = int(round(num))
            mpa_num = bar / 10.0
        mpa = f"{mpa_num:.1f}".replace(".", ",")
        return f"{mpa} ({bar})"

    @staticmethod
    def try_parse(raw: str) -> ArmatureExcelUpdate | None:
        if not raw:
            return None

        text = str(raw).strip()
        if not text.startswith("Арматура"):
            return None

        first_comma = text.find(",")
        if first_comma < 0:
            return None

        source_prefix = text[:first_comma].strip()
        tail = text[first_comma + 1 :].strip()
        if not tail:
            return None

        second_comma = tail.find(",")
        if second_comma >= 0:
            middle = tail[:second_comma].strip()
            has_registry_marker = re.search(r"\b(?:РНГС|ЕМК)\b", middle, flags=re.IGNORECASE)
            if has_registry_marker:
                description = tail[second_comma + 1 :].strip()
                # «PN 1,0» — первая запятая в хвосте; без запятой после «РНГС №…» получается
                # middle = «… PN 1» и description = «0 Мпа…» → в логах value «0».
                if description and description[0].isdigit():
                    description = tail.strip()
            else:
                description = tail
        else:
            description = tail

        if not description:
            return None

        return ExcelSpecaArmatureParser._build_update(
            source_prefix=source_prefix,
            description=description,
            source_raw=text,
        )

    @staticmethod
    def try_parse_note(source_prefix: str, note_text: str) -> ArmatureExcelUpdate | None:
        if not source_prefix or not note_text:
            return None
        text = str(note_text).strip()
        if not text:
            return None
        return ExcelSpecaArmatureParser._build_update(
            source_prefix=source_prefix.strip(),
            description=text,
            source_raw=text,
        )

    @staticmethod
    def _build_update(
        *,
        source_prefix: str,
        description: str,
        source_raw: str,
    ) -> ArmatureExcelUpdate | None:
        material_grade = ExcelSpecaArmatureParser._extract_material_grade(description)

        dn_match = re.search(r"\bDN\s*([0-9]+)\b", description, flags=re.IGNORECASE)
        pn_match = re.search(
            r"\bPN\s*([0-9]+(?:\s*[.,]\s*[0-9]+)?)\b",
            description,
            flags=re.IGNORECASE,
        )
        dn = dn_match.group(1) if dn_match else ""
        pn_raw = re.sub(r"\s+", "", (pn_match.group(1) if pn_match else "")).replace(".", ",")

        bilingual_head = bilingual_head_before_dn(description)
        russian_part = extract_russian_base_name(description)
        gost, display_ru = get_armature_gost_store().resolve(
            russian_base=russian_part,
            bilingual_head=bilingual_head,
        )

        normalized_name = display_ru
        if dn and not re.search(rf"\bDN\s*{re.escape(dn)}\b", normalized_name, flags=re.IGNORECASE):
            normalized_name = f"{normalized_name} DN{dn}".strip()
        pn = pn_raw
        pn_present_re = rf"\bPN\s*{re.escape(pn_raw)}\b"
        if "," in pn_raw:
            left, right = pn_raw.split(",", 1)
            pn_present_re = rf"\bPN\s*{re.escape(left)}\s*[.,]\s*{re.escape(right)}\b"
            normalized_name = re.sub(
                pn_present_re,
                f"PN {pn_raw}",
                normalized_name,
                flags=re.IGNORECASE,
            )
        if pn_raw and not re.search(
            pn_present_re,
            normalized_name,
            flags=re.IGNORECASE,
        ):
            normalized_name = f"{normalized_name} PN{pn_raw}".strip()
        if pn_raw:
            pn = ExcelSpecaArmatureParser._format_pn_for_storage(pn_raw)

        if not normalized_name:
            return None

        return ArmatureExcelUpdate(
            source_prefix=source_prefix,
            normalized_name=normalized_name,
            dn=dn,
            pn=pn,
            material_grade=material_grade,
            gost=gost,
            source_raw=source_raw,
        )

    @staticmethod
    def _extract_base_name(description: str) -> str:
        return extract_russian_base_name(description)

    @staticmethod
    def _extract_material_grade(description: str) -> str:
        text = str(description or "")
        # Приоритет: "материал корпуса- X" (до первой запятой/точки с запятой/точки).
        match = re.search(
            r"материал\s+корпуса\s*[-:]\s*([^,.;]+)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(" -\t'\"")

        # Fallback: содержимое первой пары скобок.
        material_match = re.search(r"\(([^()]*)\)", text)
        if material_match:
            return material_match.group(1).strip()
        return ""
