class DomainError(Exception):
    """Base exception for domain layer."""


class PipelineParseError(DomainError):
    pass


class TableExtractionError(DomainError):
    pass


class InvalidPipelineDataError(DomainError):
    pass
