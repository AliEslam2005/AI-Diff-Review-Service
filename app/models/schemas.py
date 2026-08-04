from pydantic import BaseModel, Field
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