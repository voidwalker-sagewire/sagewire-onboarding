from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import models
from app.database import Base, engine
from app.routers import events, flows, sessions


SERVICE_NAME = "SageWire Onboarding Service"
SERVICE_SLUG = "sagewire-onboarding"
SERVICE_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    """
    Initialize service resources when the application starts.

    For version 0.1.0, the service creates missing SQLite tables directly
    from SQLAlchemy metadata.

    A future production release may replace this with Alembic migrations.
    """

    Base.metadata.create_all(
        bind=engine
    )

    yield


app = FastAPI(
    title=SERVICE_NAME,
    description=(
        "A reusable, versioned onboarding engine for "
        "users, organizations, locations, and devices."
    ),
    version=SERVICE_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    flows.router,
    prefix="/api/v1",
)

app.include_router(
    sessions.router,
    prefix="/api/v1",
)

app.include_router(
    events.router,
    prefix="/api/v1",
)


@app.get(
    "/",
    tags=["Service"],
)
def service_root() -> dict[str, Any]:
    """
    Return basic service identity and navigation links.
    """

    return {
        "service": SERVICE_SLUG,
        "name": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status": "ok",
        "api_version": "v1",
        "links": {
            "health": "/health",
            "readiness": "/ready",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "flows": "/api/v1/flows",
            "sessions": "/api/v1/sessions",
            "events": "/api/v1/events",
        },
    }


@app.get(
    "/health",
    tags=["Service"],
)
def health_check() -> dict[str, str]:
    """
    Lightweight process health check.

    This endpoint does not require a database query.
    """

    return {
        "service": SERVICE_SLUG,
        "status": "ok",
        "version": SERVICE_VERSION,
    }


@app.get(
    "/ready",
    tags=["Service"],
)
def readiness_check() -> JSONResponse:
    """
    Confirm that the service can access its database.
    """

    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT 1")
            )

    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "service": SERVICE_SLUG,
                "status": "not_ready",
                "version": SERVICE_VERSION,
                "database": "unavailable",
                "error": exc.__class__.__name__,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "service": SERVICE_SLUG,
            "status": "ready",
            "version": SERVICE_VERSION,
            "database": "available",
        },
    )


@app.exception_handler(
    RequestValidationError
)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    Return a stable API error shape for invalid request data.
    """

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "REQUEST_VALIDATION_ERROR",
                "message": (
                    "The request did not pass validation."
                ),
                "path": request.url.path,
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(
    SQLAlchemyError
)
async def sqlalchemy_exception_handler(
    request: Request,
    exc: SQLAlchemyError,
) -> JSONResponse:
    """
    Prevent raw database errors from being exposed to API clients.
    """

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "DATABASE_ERROR",
                "message": (
                    "The service encountered a database error."
                ),
                "path": request.url.path,
                "details": {
                    "exception": (
                        exc.__class__.__name__
                    )
                },
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Return a consistent response for unexpected application errors.
    """

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": (
                    "The service encountered an unexpected error."
                ),
                "path": request.url.path,
                "details": {
                    "exception": (
                        exc.__class__.__name__
                    )
                },
            }
        },
    )
