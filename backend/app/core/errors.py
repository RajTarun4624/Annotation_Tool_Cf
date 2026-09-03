"""Application-level exceptions shared by crud/services and the API layer."""


class ConflictError(Exception):
    """Another actor changed the task first (surfaced to clients as HTTP 409).

    Raised from crud functions that run under a row lock when the re-check
    inside the lock fails: the task already has every response it needs,
    another reviewer holds the QA lease, or the status moved on. The
    request-scoped session is discarded by get_db, so nothing partial leaks.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
