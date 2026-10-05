from pydantic import BaseModel


class HealthOut(BaseModel):
    status: str


class ReadinessOut(BaseModel):
    status: str
    checks: dict[str, str]
