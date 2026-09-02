"""Shared pagination envelope returned by every list endpoint.

The envelope is always emitted (even when the caller asks for "everything") so
the frontend has one consistent shape to read: `{ items, total, page,
page_size }`. When no `page`/`page_size` query params are supplied the endpoint
returns the full result set in a single page — that keeps "fetch all" callers
(dropdowns, assignment pickers) working unchanged.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def paginate_query(query, page: int | None, page_size: int | None):
    """Apply LIMIT/OFFSET to a SQLAlchemy query and return (rows, total, page,
    page_size).

    `total` is the unpaginated count. When both `page` and `page_size` are
    None the full result set is returned (page=1, page_size=total).
    """
    total = query.count()

    if page is None and page_size is None:
        rows = query.all()
        return rows, total, 1, (total or 0)

    safe_page = max(1, int(page or 1))
    safe_size = min(500, max(1, int(page_size or 10)))
    offset = (safe_page - 1) * safe_size
    rows = query.offset(offset).limit(safe_size).all()
    return rows, total, safe_page, safe_size
