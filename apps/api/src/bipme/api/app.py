"""BipMe FastAPI application."""

from fastapi import FastAPI

from bipme.api.analysis import router as creator_analysis_router
from bipme.api.errors import install_error_handlers


def create_app() -> FastAPI:
    """Create the API application."""
    app = FastAPI(title="BipMe API", version="0.2.0")
    app.include_router(creator_analysis_router)
    install_error_handlers(app)

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness only; not a database readiness check."""
        return {"status": "ok"}

    return app


app = create_app()
