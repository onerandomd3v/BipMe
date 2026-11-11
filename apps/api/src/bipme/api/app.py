"""BipMe FastAPI application."""

from fastapi import FastAPI

from bipme.api.analysis import router as creator_analysis_router
from bipme.api.auth import router as auth_router
from bipme.api.creator_reports import router as creator_reports_router
from bipme.api.errors import install_error_handlers
from bipme.api.evidence import router as evidence_router
from bipme.api.history import router as history_router
from bipme.api.monitoring import router as monitoring_router
from bipme.api.postmortems import router as postmortems_router
from bipme.api.publications import router as publications_router


def create_app() -> FastAPI:
    """Create the API application."""
    app = FastAPI(title="BipMe API", version="0.2.0")
    app.include_router(auth_router)
    app.include_router(creator_analysis_router)
    app.include_router(creator_reports_router)
    app.include_router(publications_router)
    app.include_router(postmortems_router)
    app.include_router(monitoring_router)
    app.include_router(history_router)
    app.include_router(evidence_router)
    install_error_handlers(app)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness only; not a database readiness check."""
        return {"status": "ok"}

    return app


app = create_app()
