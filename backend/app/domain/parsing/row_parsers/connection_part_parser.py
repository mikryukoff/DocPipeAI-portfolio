from backend.app.domain.models.specification import ConnectionPart
from backend.app.domain.parsing.specification.specification_item_formatter import (
    SpecificationPartsFormatter,
)
from .base import SpecRowParser


class ConnectionPartRowParser(SpecRowParser):
    def parse(self, line: list[str]):
        if not line[0].isdigit():
            return None

        position = int(line[0])
        name = " ".join(line[1:-2]).strip()
        unit = line[-2]
        quantity = float(line[-1].replace(",", "."))

        pipe = ConnectionPart(position, name, unit, quantity)
        SpecificationPartsFormatter.format(name, pipe)
        pipe.name = pipe.name.split(" по ")[0]
        return pipe