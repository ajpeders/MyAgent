"""News service errors."""


class NewsServiceError(Exception):
    pass


class SourceNotFoundError(NewsServiceError):
    pass
