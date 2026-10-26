from abc import ABC, abstractmethod


class TextSource(ABC):

    @abstractmethod
    def extract_text(self) -> list[dict]:
        """
        Возвращает список:
        [{page: int, text: str, meta: dict}]
        """
        pass
