"""``GET /annotation/taxonomy`` — the dropdown vocabulary for the annotation
form, served from the single source of truth ``app.core.taxonomy`` so the
list can be edited without touching the UI."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.core.taxonomy import taxonomy_payload

router = APIRouter()


@router.get("/taxonomy")
def read_taxonomy(
    _: Annotated[dict, Depends(get_current_user)],
) -> dict[str, Any]:
    """Option lists (value + label) for every annotation field, the
    subcategories grouped by attack type, severity levels and defaults.
    Any authenticated user may read it."""
    return taxonomy_payload()
