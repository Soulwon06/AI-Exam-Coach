from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import AppError
from app.database import SessionLocal, init_db
from app.routers import auth, courses, learning, materials, ranking, study_units

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = settings.api_v1_prefix

app.include_router(courses.router, prefix=API_PREFIX, tags=["courses"])
app.include_router(auth.router, prefix=API_PREFIX, tags=["auth"])
app.include_router(materials.router, prefix=API_PREFIX, tags=["materials"])
app.include_router(study_units.router, prefix=API_PREFIX, tags=["study-units"])
app.include_router(learning.router, prefix=API_PREFIX, tags=["learning"])
app.include_router(ranking.router, prefix=API_PREFIX, tags=["ranking"])


@app.exception_handler(AppError)
async def app_error_handler(request, exc: AppError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status_code,
        content={"data": None, "error": {"code": exc.detail["code"], "message": exc.detail["message"]}},
    )


@app.get(API_PREFIX + "/health")
def health():
    return {
        "data": {
            "status": "ok",
            "maxUploadMb": settings.max_upload_mb,
            "maxWorkers": settings.max_workers,
        },
        "error": None,
    }


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        from app.services.auth_service import provision_configured_account

        provision_configured_account(db)
    finally:
        db.close()
