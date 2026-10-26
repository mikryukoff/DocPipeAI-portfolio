import re
from backend.app.domain.models.specification import Armature
from backend.app.domain.parsing.armature_gost_store import get_armature_gost_store
from backend.app.domain.parsing.armature_text import (
    bilingual_head_before_dn,
    extract_russian_base_name,
)
from backend.app.shared.pipeline_number_format import format_with_number_sign
from .base import SpecRowParser

# «Материал: корпус - А351 CF3M; …» — марка корпуса до «;»
_CORPUS_MATERIAL_RE = re.compile(
    r"материал\s*:\s*корпус\s*-\s*(.+?)\s*;",
    re.IGNORECASE | re.DOTALL,
)


class ArmatureRowParser(SpecRowParser):

    @staticmethod
    def _extract_material_grade_corpus(description: str) -> str:
        m = _CORPUS_MATERIAL_RE.search(description or "")
        if not m:
            return ""
        return m.group(1).strip()

    def parse(self, line: list[str], pipeline_name: str):
        if not line[0].isdigit():
            return None

        position = int(line[0])
        full_name = line[1].strip()
        unit = line[-2]
        quantity = float(line[-1].replace(",", "."))

        match = re.search(r"\((.+?)\)", full_name)
        if match:
            full_name = full_name.split("(")[0].strip()

        parts = re.split(r"[,.](?=\s)", full_name)
        segment = parts[0].strip() if parts else full_name.strip()

        dn_match = re.search(r"DN\s?(\d+)", segment, re.IGNORECASE)
        pn_match = re.search(r"PN\s?(\d+)", segment, re.IGNORECASE)
        dn = dn_match.group(1) if dn_match else ""
        pn_raw = pn_match.group(1) if pn_match else ""

        bilingual_head = bilingual_head_before_dn(segment)
        russian_part = extract_russian_base_name(segment)
        gost, display_ru = get_armature_gost_store().resolve(
            russian_base=russian_part,
            bilingual_head=bilingual_head,
        )

        normalized_name = display_ru
        if dn and not re.search(
            rf"\bDN\s*{re.escape(dn)}\b", normalized_name, flags=re.IGNORECASE
        ):
            normalized_name = f"{normalized_name} DN{dn}".strip()
        if pn_raw and not re.search(
            rf"\bPN\s*{re.escape(pn_raw)}\b", normalized_name, flags=re.IGNORECASE
        ):
            normalized_name = f"{normalized_name} PN{pn_raw}".strip()

        armature = Armature(
            position=position,
            name=normalized_name,
            unit=unit,
            quantity=quantity,
        )

        if dn:
            armature.dn = dn

        if pn_raw:
            pn = int(pn_raw)
            armature.pn = f"{str(pn / 10).replace('.', ',')} ({pn})"

        if gost:
            armature.gost = gost

        mg = self._extract_material_grade_corpus(line[1].strip())
        if mg:
            armature.material_grade = mg

        armature.location = f"т-д {format_with_number_sign(pipeline_name)}"

        return armature
