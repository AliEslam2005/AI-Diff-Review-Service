import time
from fastapi import FastAPI, Depends, Header
from fastapi.responses import JSONResponse
from app.models.schemas import HealthResponse, SpecResponse, Limits, ReviewRequest

app = FastAPI(title="AI Diff Review Service")

START_TIME = time.time()
SERVICE_TOKEN = "my-test-token"  # We'll put this in a .env file later

# --- Auth Middleware ---
def verify_token(authorization: str = Header(None)):
    expected_header = f"Bearer {SERVICE_TOKEN}"
    if not authorization or authorization != expected_header:
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "unauthorized", "message": "Missing or invalid token"}}
        )
    return authorization

# --- Public Endpoints ---
@app.get("/health", response_model=HealthResponse)
async def health_check():
    uptime = int(time.time() - START_TIME)
    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptimeSeconds=uptime
    )

@app.get("/spec", response_model=SpecResponse)
async def get_spec():
    return SpecResponse(
        specVersion="1.0",
        providers=["mock", "llm"],
        limits=Limits(
            maxPayloadBytes=1048576,
            chunkBytes=65536,
            maxConcurrentJobs=4,
            rateLimitPerMinute=30
        )
    )

# --- Protected Endpoint ---
@app.post("/v1/reviews", status_code=202)
async def submit_review(request: ReviewRequest, token: str | JSONResponse = Depends(verify_token)):
    if isinstance(token, JSONResponse):
        return token
    return {"jobId": "temp-job-id-123", "status": "queued"}