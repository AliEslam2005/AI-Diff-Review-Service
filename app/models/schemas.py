from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional

# --- Public Endpoints ---
class HealthResponse(BaseModel):
    status: str
    version: str
    uptimeSeconds: int

class Limits(BaseModel):
    maxPayloadBytes: int
    chunkBytes: int
    maxConcurrentJobs: int
    rateLimitPerMinute: int

class SpecResponse(BaseModel):
    specVersion: str
    providers: list[str]
    limits: Limits

# --- Review Request Payload ---
class ReviewOptions(BaseModel):
    provider: Literal["mock", "llm"] = "mock"
    maxFindings: int = Field(default=100)

class ReviewRequest(BaseModel):
    diff: str
    options: Optional[ReviewOptions] = Field(default_factory=ReviewOptions)

    @field_validator("diff")
    @classmethod
    def diff_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("diff must not be empty")
        return v