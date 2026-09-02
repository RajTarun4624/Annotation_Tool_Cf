from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.feature import FeatureResponse
from app.models.user import Feature

router = APIRouter()


@router.get("/", response_model=list[FeatureResponse])
def list_features(db: Annotated[Session, Depends(get_db)]) -> list[FeatureResponse]:
    features = db.query(Feature).order_by(Feature.order.asc()).all()
    items = []
    for f in features:
        items.append(
            FeatureResponse(
                id=f.key, # Features use key as primary key in my model
                key=f.key,
                name=f.name,
                description=f.description or "",
                icon=f.icon or "AppstoreOutlined",
                order=f.order or 0,
            )
        )
    return items
