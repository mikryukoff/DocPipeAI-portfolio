from abc import ABC, abstractmethod


class TableSource(ABC):
    @abstractmethod
    async def extract_tables(self) -> list:
        pass
