from __future__ import annotations

from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import require_token
from .config import load_settings, save_rdma_config
from .db import enqueue, get_job, init_db, list_jobs
from .jobs import validate_request
from .models import JobCreate, LoginCheck, RdmaConfigUpdate
from .provider import get_provider, ProviderError

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
init_db()

app = FastAPI(title="OKE RDMA Control Center", version="2.3.0", docs_url=None, redoc_url=None)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    try:
        load_settings()
        init_db()
        return {"status": "ready", "mode": load_settings().mode}
    except Exception as exc:
        return JSONResponse(status_code=503, content={"status": "not-ready", "error": str(exc)})


@app.post("/api/v1/session", response_model=LoginCheck, dependencies=[Depends(require_token)])
def session_check():
    return LoginCheck()


@app.get("/api/v1/environment", dependencies=[Depends(require_token)])
def environment():
    settings = load_settings()
    try:
        return get_provider(settings).environment()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/preflight", dependencies=[Depends(require_token)])
def preflight():
    settings = load_settings()
    try:
        return get_provider(settings).preflight()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/rdma/discovery", dependencies=[Depends(require_token)])
def rdma_discovery():
    settings = load_settings()
    try:
        return get_provider(settings).rdma_discovery()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/nodes", dependencies=[Depends(require_token)])
def node_diagnostics():
    settings = load_settings()
    try:
        return get_provider(settings).node_diagnostics()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/rdma/config", dependencies=[Depends(require_token)])
def rdma_config():
    settings = load_settings()
    try:
        locks = get_provider(settings).configuration_status()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "config": settings.rdma_config(),
        "configured": settings.rdma_configured,
        "locks": locks,
        "documentation": {
            "ubuntu_node_packages": "https://docs.oracle.com/en-us/iaas/Content/ContEng/Concepts/contengCompatibilitymatrix_topic.htm",
            "ubuntu_custom_workers": "https://docs.oracle.com/en-us/iaas/Content/ContEng/Tasks/contengcreatingubuntubasedworkernodes.htm",
        },
    }


@app.put("/api/v1/rdma/config", dependencies=[Depends(require_token)])
def update_rdma_config(req: RdmaConfigUpdate):
    settings = load_settings()
    provider = get_provider(settings)
    try:
        locks = provider.configuration_status()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    old = settings.rdma_config()
    new = req.model_dump()
    try:
        provider.validate_rdma_selection(new)
    except ProviderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    hardware_fields = {"rdma_pf_name", "rdma_mtu", "rdma_vfs_per_node", "rdma_resource_name"}
    changed_hardware = [name for name in hardware_fields if old.get(name) != new.get(name)]
    if locks.get("hardware_fields_locked") and changed_hardware:
        raise HTTPException(
            status_code=409,
            detail=(
                "The VF policy already exists, so PF/MTU/VF/resource settings are locked. "
                "This quickstart intentionally does not perform destructive policy migration from the web UI."
            ),
        )
    if locks.get("network_fields_locked") and old.get("rdma_ip_pool_cidr") != new.get("rdma_ip_pool_cidr"):
        raise HTTPException(
            status_code=409,
            detail=(
                "The VF network already exists, so its IP pool is locked. "
                "Remove/migrate the network through a reviewed operator procedure before changing the pool."
            ),
        )

    try:
        saved = save_rdma_config(new)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Unable to persist RDMA configuration: {exc}") from exc
    return {
        "saved": True,
        "configured": saved.rdma_configured,
        "config": saved.rdma_config(),
        "locks": locks,
    }


@app.get("/api/v1/jobs", dependencies=[Depends(require_token)])
def jobs():
    return {"items": list_jobs()}


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_token)])
def job(job_id: str):
    try:
        return get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.post("/api/v1/jobs", dependencies=[Depends(require_token)])
def create_job(req: JobCreate):
    settings = load_settings()
    try:
        validate_request(settings, req.action, req.confirmation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return enqueue(req.action, req.confirmation)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
