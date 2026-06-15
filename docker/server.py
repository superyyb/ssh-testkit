from collections import deque
from fastapi import FastAPI, Request
import logging
import os
import time
import psutil
import uvicorn

app = FastAPI()

os.makedirs("/home/testuser/app_logs", exist_ok=True)

logging.basicConfig(
    filename="/home/testuser/app_logs/app.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

_start_time     = time.time()
_request_count  = 0
_error_count    = 0
_response_times = deque(maxlen=1000)  # auto-drops oldest entries


@app.middleware("http")
async def track_requests(request: Request, call_next):
    global _request_count, _error_count
    start    = time.time()
    response = await call_next(request)
    duration = time.time() - start

    _request_count += 1
    _response_times.append(duration)
    if response.status_code >= 500:
        _error_count += 1
    return response


@app.get("/health")
def health():
    logging.info("Health check requested")
    return {"status": "ok", "version": "1.0.0"}


@app.get("/status")
def status():
    logging.info("Status check requested")
    db_status = "connected"
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "postgres"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "testframework"),
            user=os.getenv("DB_USER", "testuser"),
            password=os.getenv("DB_PASSWORD", "testpass"),
            connect_timeout=2,
        )
        conn.close()
    except Exception:
        db_status = "unreachable"
    return {"db": db_status, "service": "running"}


@app.get("/metrics")
def metrics():
    logging.info("Metrics requested")
    recent = list(_response_times)[-100:]
    return {
        "uptime_seconds":  round(time.time() - _start_time),
        "request_count":   _request_count,
        "error_count":     _error_count,
        "error_rate":      round(_error_count / max(_request_count, 1), 4),
        "avg_response_ms": round(sum(recent) / max(len(recent), 1) * 1000, 2),
        "cpu_percent":     psutil.cpu_percent(interval=0.1),
        "memory_percent":  psutil.virtual_memory().percent,
        "memory_used_mb":  psutil.virtual_memory().used // 1024 // 1024,
        "disk_percent":    psutil.disk_usage("/").percent,
    }


if __name__ == "__main__":
    logging.info("Server startup complete on port 8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
