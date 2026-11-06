"""BipMe FastAPI application."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create the API application."""
    app = FastAPI(title="BipMe API", version="0.1.0")

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness only; not a database readiness check."""
        return {"status": "ok"}

    return app


app = create_app()
