from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from apps.mcp.server import mcp, mcp_http_app

from .admin_routes import router as admin_router
from .auth_routes import router as auth_router
from .billing_routes import router as billing_router
from .config import get_settings
from .database import SessionLocal, init_database
from .routes import router
from .seed import seed_application
from .storage import MediaStorage
from .workflow import WorkflowManager

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("avs.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    with SessionLocal() as session:
        seed_application(session, settings)
    app.state.workflow = WorkflowManager(settings)
    app.state.workflow.resume_pending()
    async with mcp.session_manager.run():
        yield
        for task in list(app.state.workflow.tasks.values()):
            if not task.done():
                task.cancel()


app = FastAPI(
    title="Agentic Video Studio API",
    version="0.1.0",
    description="Evidence-first, tenant-aware production orchestration for short-form video.",
    openapi_version="3.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or "Request failed")
        code = str(detail.get("code") or "request_failed")
        details = {key: value for key, value in detail.items() if key not in {"code", "message"}} or None
    else:
        message = str(detail)
        code = "request_failed"
        details = None
    log_method = logger.error if exc.status_code >= 500 else logger.warning
    log_method(
        "request_rejected method=%s path=%s status=%s code=%s request_id=%s",
        request.method,
        request.url.path,
        exc.status_code,
        code,
        request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id,
                "retryable": exc.status_code >= 500,
            }
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
    errors = []
    for item in exc.errors():
        cleaned = dict(item)
        location = [str(part).lower() for part in cleaned.get("loc") or []]
        if any(
            marker in part
            for part in location
            for marker in ("password", "secret", "token", "verification", "code")
        ):
            cleaned.pop("input", None)
        if cleaned.get("ctx"):
            cleaned["ctx"] = {
                key: str(value) if isinstance(value, BaseException) else value
                for key, value in cleaned["ctx"].items()
            }
        errors.append(jsonable_encoder(cleaned))
    logger.warning(
        "request_validation_failed method=%s path=%s status=422 request_id=%s",
        request.method,
        request.url.path,
        request_id,
    )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "details": {"errors": errors},
                "request_id": request_id,
                "retryable": False,
            }
        },
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": "Agentic Video Studio", "docs": "/docs", "health": "/v1/health"}


@app.get("/media/{asset_path:path}", include_in_schema=False)
def media(
    asset_path: str,
    org: str = Query(min_length=3, max_length=64),
    expires: int = Query(gt=0),
    sig: str = Query(min_length=64, max_length=64),
):
    storage = MediaStorage(settings)
    public_path = f"/media/{asset_path}"
    if not storage.verify_signed_path(public_path, org, expires, sig):
        raise HTTPException(403, "Media link is invalid or expired")
    local_path = storage.resolve_local(asset_path)
    if not local_path:
        raise HTTPException(404, "Media asset not found")
    if local_path.is_file():
        return FileResponse(local_path)
    remote = storage.download_bytes(asset_path)
    if not remote:
        raise HTTPException(404, "Media asset not found")
    body, content_type = remote
    return Response(body, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


app.include_router(router)
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(admin_router)
app.mount("/", mcp_http_app, name="mcp")
