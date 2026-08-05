import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header
from fastapi.responses import JSONResponse
from app.models.schemas import HealthResponse, SpecResponse, Limits, ReviewRequest
from app.services.jobs import create_job, worker_task, JOBS_DB

START_TIME = time.time()
SERVICE_TOKEN = "my-test-token"

# --- Lifespan Manager (Starts our 4 Background Workers) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start 4 concurrent worker tasks[cite: 2]
    workers = [asyncio.create_task(worker_task()) for _ in range(4)]
    yield
    # Clean up on shutdown
    for w in workers:
        w.cancel()

app = FastAPI(title="AI Diff Review Service", lifespan=lifespan)

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
    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptimeSeconds=int(time.time() - START_TIME)
    )

@app.get("/spec", response_model=SpecResponse)
async def get_spec():
    return SpecResponse(
        specVersion="1.0",
        providers=["mock", "llm"],
        limits=Limits(maxPayloadBytes=1048576, chunkBytes=65536, maxConcurrentJobs=4, rateLimitPerMinute=30)
    )

# --- Protected API Routes ---
@app.post("/v1/reviews")
async def submit_review(
    request: ReviewRequest, 
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    token: str | JSONResponse = Depends(verify_token)
):
    if isinstance(token, JSONResponse): return token
    
    # Pass to our queue system
    job_id, status_code, error = create_job(request.diff, request.options.model_dump(), idempotency_key)
    
    if error:
        return JSONResponse(status_code=status_code, content=error)
        
    return JSONResponse(status_code=status_code, content={"jobId": job_id, "status": "queued"})

@app.get("/v1/reviews/{job_id}")
async def get_review_status(job_id: str, token: str | JSONResponse = Depends(verify_token)):
    if isinstance(token, JSONResponse): return token
    
    job = JOBS_DB.get(job_id)
    if not job:
        # Unknown jobId -> 404[cite: 2]
        return JSONResponse(
            status_code=404, 
            content={"error": {"code": "not_found", "message": "Job not found"}}
        )
        
    # Return the exact schema requested
    return {
        "jobId": job["jobId"],
        "status": job["status"],
        "findings": job["findings"],
        "usage": job["usage"]
    }