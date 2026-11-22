import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import psutil
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from incidentlab.config import ROOT, load_settings
from incidentlab.domain import InvestigationRequest
from incidentlab.llm import probe
from incidentlab.tools import ToolError
from incidentlab.workflow import Workflow

app = FastAPI(title="IncidentLab", version="0.2.0", description="Connected read-only incident investigation")
CPU = Gauge("incidentlab_process_cpu_percent", "Process CPU usage; may exceed 100 on multiple cores")
RAM = Gauge("incidentlab_process_memory_bytes", "Resident RAM used by the API process")
PROCESS = psutil.Process()
RUN_LOCK = threading.BoundedSemaphore(1)
STATIC = ROOT / "src/incidentlab/static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@lru_cache(maxsize=1)
def get_workflow():
    return Workflow()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={
        "Content-Security-Policy": "default-src 'self'; object-src 'none'; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/health")
def health():
    return {"status": "ok", "stage": "first-connected-scenario", "workflow_implemented": True}


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
            "workflow_implemented": True}


@app.get("/incidents")
def incidents(workflow: Workflow = Depends(get_workflow)):
    return [incident.model_dump(mode="json") for incident in workflow.incidents.list_incidents()]


@app.post("/investigations")
def investigate(request: InvestigationRequest, workflow: Workflow = Depends(get_workflow)):
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429, "An investigation is already running; retry after it completes")
    try:
        try:
            result = workflow.run(request.incident_id)
        except (FileNotFoundError, ToolError):
            raise HTTPException(404, "Unknown or invalid incident") from None
        return JSONResponse(result, status_code=503 if result["status"] == "error" else 200)
    finally:
        RUN_LOCK.release()


@app.get("/investigations/{run_id}")
def investigation(run_id: str, workflow: Workflow = Depends(get_workflow)):
    try:
        return workflow.runs.read(run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Run not found") from None


@app.get("/metrics", include_in_schema=False)
def metrics():
    CPU.set(PROCESS.cpu_percent())
    RAM.set(PROCESS.memory_info().rss)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
