from abc import ABC, abstractmethod


class SpecRowParser(ABC):

    @abstractmethod
    def parse(self, line: list[str]):
        pass
