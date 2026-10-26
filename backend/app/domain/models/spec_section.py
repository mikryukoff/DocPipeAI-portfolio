from enum import Enum


class SpecSection(str, Enum):
    PIPELINE_ARMATURE = "pipeline_armature"
    INSTRUMENT_EMBEDMENT = "instrument_embedments"
    PIPES = "pipes"
    CONNECTION_PARTS = "connection_parts"
    FLANGES = "flanges"
    SUPPORTS = "supports"
