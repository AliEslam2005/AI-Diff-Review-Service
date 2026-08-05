import asyncio
import hashlib
import json
import uuid

from app.providers.mock import scan_diff_with_mock
from app.providers.llm import scan_diff_with_llm
from app.services.chunking import chunk_diff

# --- In-Memory State Stores ---
JOBS_DB = {}
IDEMPOTENCY_DB = {}
CACHE_DB = {}

job_queue = asyncio.Queue()

def generate_payload_hash(diff: str, options: dict) -> str:
    payload = {"diff": diff, "options": options}
    payload_str = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

def create_job(diff: str, options: dict, idempotency_key: str | None = None) -> tuple[str | None, int, dict | None]:
    payload_hash = generate_payload_hash(diff, options)
    
    # 1. Idempotency Check[cite: 2]
    if idempotency_key:
        if idempotency_key in IDEMPOTENCY_DB:
            existing = IDEMPOTENCY_DB[idempotency_key]
            if existing["hash"] == payload_hash:
                return existing["jobId"], 202, None
            else:
                return None, 409, {"error": {"code": "idempotency_conflict", "message": "Idempotency key used with different payload"}}

    # 2. Caching Check[cite: 2]
    if payload_hash in CACHE_DB:
        cached_job_id = CACHE_DB[payload_hash]
        if idempotency_key:
            IDEMPOTENCY_DB[idempotency_key] = {"hash": payload_hash, "jobId": cached_job_id}
            
        if cached_job_id in JOBS_DB:
             JOBS_DB[cached_job_id]["usage"]["cacheHit"] = True
             
        return cached_job_id, 202, None

    # 3. Create New Job
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    input_bytes = len(diff.encode('utf-8'))

    JOBS_DB[job_id] = {
        "jobId": job_id,
        "status": "queued",
        "findings": [],
        "usage": {"inputBytes": input_bytes, "chunks": 0, "cacheHit": False},
        "events": [{"event": "status", "data": json.dumps("queued")}],
        "diff": diff,          
        "options": options     
    }
    
    if idempotency_key:
        IDEMPOTENCY_DB[idempotency_key] = {"hash": payload_hash, "jobId": job_id}
        
    CACHE_DB[payload_hash] = job_id
    job_queue.put_nowait(job_id)
    
    return job_id, 202, None

async def worker_task():
    while True:
        job_id = await job_queue.get()
        job = JOBS_DB.get(job_id)
        
        if job and job["status"] == "queued":
            job["status"] = "running"
            job["events"].append({"event": "status", "data": json.dumps("running")})
            await asyncio.sleep(0)
            
            try:
                diff_text = job["diff"]
                options = job["options"]
                provider_type = options.get("provider", "mock")
                max_findings = options.get("maxFindings", 100)

                # Split diff into strictly compliant chunks[cite: 2]
                chunks = chunk_diff(diff_text, max_bytes=65536)
                job["usage"]["chunks"] = len(chunks)

                all_findings = []
                if provider_type == "mock":
                    for chunk in chunks:
                        chunk_findings = await asyncio.to_thread(scan_diff_with_mock, chunk)
                        all_findings.extend(chunk_findings)
                elif provider_type == "llm":
                    for chunk in chunks:
                        # Send each chunk to Gemini
                        chunk_findings = await asyncio.to_thread(scan_diff_with_llm, chunk)
                        all_findings.extend(chunk_findings)
                else:
                    all_findings = []

                # Ensure global sorting across chunks[cite: 2]
                all_findings.sort(key=lambda x: (x["path"], x["line"], x["ruleId"]))
                
                # Ensure global deduplication across chunks[cite: 2]
                unique_findings = []
                seen_ids = set()
                for finding in all_findings:
                    if finding["id"] not in seen_ids:
                        seen_ids.add(finding["id"])
                        unique_findings.append(finding)

                # Apply truncation[cite: 2]
                job["findings"] = unique_findings[:max_findings]
                
                for finding in job["findings"]:
                    job["events"].append({"event": "finding", "data": json.dumps(finding)})

                job["status"] = "done"
                done_payload = {"total": len(job["findings"]), "usage": job["usage"]}
                job["events"].append({"event": "done", "data": json.dumps(done_payload)})

            except Exception as e:
                job["status"] = "failed"
                job["error"] = {"code": "internal", "message": str(e)[:300]}
                job["events"].append({"event": "status", "data": json.dumps("failed")})
                
            finally:
                job.pop("diff", None)
                job.pop("options", None)
            
        job_queue.task_done()