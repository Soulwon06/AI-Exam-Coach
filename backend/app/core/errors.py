from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


class AuthRequiredError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__("AUTH_REQUIRED", message, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden"):
        super().__init__("FORBIDDEN", message, status_code=403)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__("RESOURCE_NOT_FOUND", message, status_code=404)


class InvalidRequestError(AppError):
    def __init__(self, message: str = "Invalid request"):
        super().__init__("INVALID_REQUEST", message, status_code=400)


class CourseNotReadyError(AppError):
    def __init__(self, message: str = "Course is not ready yet"):
        super().__init__("COURSE_NOT_READY", message, status_code=409)


class MaterialProcessingError(AppError):
    def __init__(self, message: str = "Material still processing"):
        super().__init__("MATERIAL_PROCESSING", message, status_code=409)


class MaterialProcessingFailedError(AppError):
    def __init__(self, message: str = "Material processing failed"):
        super().__init__("MATERIAL_PROCESSING_FAILED", message, status_code=422)


class AIProcessingFailedError(AppError):
    def __init__(self, message: str = "AI processing failed"):
        super().__init__("AI_PROCESSING_FAILED", message, status_code=502)


class QuestionNotAvailableError(AppError):
    def __init__(self, message: str = "No question available"):
        super().__init__("QUESTION_NOT_AVAILABLE", message, status_code=404)


class SessionExpiredError(AppError):
    def __init__(self, message: str = "Learning session expired"):
        super().__init__("SESSION_EXPIRED", message, status_code=410)


class InternalError(AppError):
    def __init__(self, message: str = "Internal error"):
        super().__init__("INTERNAL_ERROR", message, status_code=500)
