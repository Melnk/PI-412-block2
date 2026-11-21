from concurrent.futures import ThreadPoolExecutor

import psutil
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from incidentlab.config import load_settings
from incidentlab.llm import probe

app = FastAPI(title="IncidentLab", version="0.1.0", description="Development foundation; workflow pending")
CPU = Gauge("incidentlab_process_cpu_percent", "Process CPU usage; may exceed 100 on multiple cores")
RAM = Gauge("incidentlab_process_memory_bytes", "Resident RAM used by the API process")
PROCESS = psutil.Process()


@app.get("/health")
def health():
    return {"status": "ok", "stage": "development-foundation", "workflow_implemented": False}


@app.get("/models")
def models():
    settings = load_settings()
    return {"engine": settings.engine, "roles": settings.roles,
            "models": [model.model_dump() for model in settings.models]}


@app.get("/readiness")
def readiness():
    settings = load_settings()
    with ThreadPoolExecutor(max_workers=3) as pool:
        statuses = list(pool.map(probe, settings.models))
    return {"models_ready": all(status["ready"] for status in statuses), "models": statuses,
            "workflow_implemented": False}


@app.get("/metrics", include_in_schema=False)
def metrics():
    CPU.set(PROCESS.cpu_percent())
    RAM.set(PROCESS.memory_info().rss)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
