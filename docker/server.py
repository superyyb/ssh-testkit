from fastapi import FastAPI
from fastapi.responses import JSONResponse
import logging
import os
import uvicorn

app = FastAPI()

os.makedirs("/home/testuser/app_logs", exist_ok=True)

logging.basicConfig(
    filename="/home/testuser/app_logs/app.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


@app.get("/health")
def health():
    logging.info("Health check requested")
    return {"status": "ok", "version": "1.0.0"}


@app.get("/status")
def status():
    logging.info("Status check requested")
    return {"db": "connected", "cache": "ok", "service": "running"}


@app.get("/metrics")
def metrics():
    logging.info("Metrics requested")
    return {"uptime": 3600, "requests_total": 42, "errors": 0}


if __name__ == "__main__":
    logging.info("Server startup complete on port 8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
