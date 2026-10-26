import re
from dataclasses import dataclass

from backend.app.shared.pipeline_name_extract import (
    extract_line_id_token,
    is_plausible_line_designation,
)


@dataclass
class FlowDirectionExcelUpdate:
    pipeline_name: str
    flow_direction_text: str
    source_raw: str


class ExcelFlowDirectionParser:
    _PIPELINE_RE = re.compile(
        r"[A-Z]{2}\d{2}-\d{5}(?:\.\d+)?-[A-Z]{3}-\d{2,3}-[A-Z0-9-]+(?:-[A-Z]{2})?"
    )
    _LINE_LABEL_FLOW_RE = re.compile(
        r"линия\s+([^:;(\n\r]+?)\s*:\s*(.+)",
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def try_parse(cls, raw: str) -> FlowDirectionExcelUpdate | None:
        if not raw:
            return None

        text = str(raw).strip()
        pipeline_match = cls._PIPELINE_RE.search(text)
        if not pipeline_match:
            line_flow = cls._LINE_LABEL_FLOW_RE.search(text)
            if line_flow:
                line_id = extract_line_id_token(f"линия {line_flow.group(1)}")
                flow_direction_text = line_flow.group(2).split(";", 1)[0].strip()
                if (
                    line_id
                    and is_plausible_line_designation(line_id)
                    and flow_direction_text
                ):
                    return FlowDirectionExcelUpdate(
                        pipeline_name=line_id,
                        flow_direction_text=flow_direction_text,
                        source_raw=text,
                    )
            return None
        pipeline_name = pipeline_match.group(0)
        end_code = pipeline_match.end()

        # Классический формат сводки: есть «:» и «;» (параметры после первого «;»).
        if ":" in text and ";" in text:
            description_start = text.find(":", end_code)
            if description_start != -1:
                flow_direction_text = text[description_start + 1 :].split(";", 1)[0].strip()
                if flow_direction_text:
                    return FlowDirectionExcelUpdate(
                        pipeline_name=pipeline_name,
                        flow_direction_text=flow_direction_text,
                        source_raw=text,
                    )

        # Без «Линия N:» и без «;»: «CODE: от … до …» или параметры только через запятую.
        colon_after = text.find(":", end_code)
        if colon_after != -1:
            flow_direction_text = text[colon_after + 1 :].strip()
            if ";" in flow_direction_text:
                flow_direction_text = flow_direction_text.split(";", 1)[0].strip()
            if flow_direction_text and flow_direction_text != ";":
                return FlowDirectionExcelUpdate(
                    pipeline_name=pipeline_name,
                    flow_direction_text=flow_direction_text,
                    source_raw=text,
                )

        # Без двоеточия после кода: «… линия CODE от … до …» или «CODE от …».
        tail = text[end_code:].strip().lstrip(":").strip()
        low = tail.lower()
        if tail and (
            low.startswith("от")
            or low.startswith("до")
            or " от " in low[:240]
            or " до " in low[:240]
            or low.startswith("лини")
        ):
            return FlowDirectionExcelUpdate(
                pipeline_name=pipeline_name,
                flow_direction_text=tail,
                source_raw=text,
            )
        return None
