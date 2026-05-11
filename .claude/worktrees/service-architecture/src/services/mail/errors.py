"""Mail service errors."""
from services.errors import ServiceError


class MailServiceError(ServiceError):
    pass


class NoActiveSessionError(MailServiceError):
    pass


class ImapConnectionError(MailServiceError):
    pass


class EmailNotFoundError(MailServiceError):
    pass


class FolderResolutionError(MailServiceError):
    pass