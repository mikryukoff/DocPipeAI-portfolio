from backend.app.domain.models.spec_section import SpecSection


class SectionDetector:
    def detect(self, title: str) -> SpecSection | None:
        if "Арматура трубопроводов" in title:
            return SpecSection.PIPELINE_ARMATURE

        if "Закладная" in title:
            return SpecSection.INSTRUMENT_EMBEDMENT

        if title == "Трубы":
            return SpecSection.PIPES

        if "Соединительные детали трубопроводов" in title:
            return SpecSection.CONNECTION_PARTS

        if "Фланцы" in title:
            return SpecSection.FLANGES

        if "Опоры" in title:
            return SpecSection.SUPPORTS

        return None

