"""Application-level errors mapped to HTTP responses by the API layer."""


class AppError(Exception):
    status_code = 400
    code = "APP_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "FORBIDDEN"
