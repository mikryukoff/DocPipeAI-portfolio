from abc import ABC, abstractmethod


class TableWriter(ABC):
    @abstractmethod
    def write(
        self,
        rows: list[list[str]],
        page: int,
        index: int,
    ) -> None:
        pass
