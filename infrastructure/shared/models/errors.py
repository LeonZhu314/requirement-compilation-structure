"""A terminal provider failure is not a rejected application proposal."""


class ModelServiceError(RuntimeError):
    """Surface exhausted transport recovery without compiling incomplete requirements."""

    def __init__(self, message, *, status_code=None, request_id=None):
        super().__init__(message)
        self.feedback = {"status_code": status_code, "provider_request_id": request_id}
