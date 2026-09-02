from pydantic import BaseModel


class FeatureResponse(BaseModel):
    id: str
    key: str
    name: str
    description: str
    icon: str
    order: int

    model_config = {"from_attributes": True}
