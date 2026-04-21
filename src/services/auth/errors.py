"""Auth service errors."""
from services.errors import ServiceError


class AuthServiceError(ServiceError):
    pass


class UserExistsError(AuthServiceError):
    pass


class InvalidCredentialsError(AuthServiceError):
    pass


class UserNotFoundError(AuthServiceError):
    pass


class DecryptionError(AuthServiceError):
    pass