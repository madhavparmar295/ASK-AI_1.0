class ServiceError(Exception):
    """Business-rule error. main.py turns it into a JSON response with this status."""

    def __init__(self, status: int, detail: str, **extra):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extra = extra
