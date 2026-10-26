from backend.app.domain.models.spec_section import SpecSection
from backend.app.domain.parsing.row_parsers.pipe_parser import PipeRowParser
from backend.app.domain.parsing.row_parsers.armature_parser import ArmatureRowParser
from backend.app.domain.parsing.row_parsers.instrument_embedment_parser import (
    InstrumentEmbedmentRowParser,
)
from backend.app.domain.parsing.row_parsers.support_parser import SupportRowParser
from backend.app.domain.parsing.row_parsers.connection_part_parser import (
    ConnectionPartRowParser,
)
from backend.app.domain.parsing.row_parsers.flange_parser import FlangeRowParser


class SpecRowParserRegistry:
    def __init__(self):
        self._parsers = {
            SpecSection.PIPES: PipeRowParser(),
            SpecSection.PIPELINE_ARMATURE: ArmatureRowParser(),
            SpecSection.INSTRUMENT_EMBEDMENT: InstrumentEmbedmentRowParser(),
            SpecSection.SUPPORTS: SupportRowParser(),
            SpecSection.CONNECTION_PARTS: ConnectionPartRowParser(),
            SpecSection.FLANGES: FlangeRowParser(),
        }

    def get(self, section: SpecSection):
        return self._parsers.get(section)

