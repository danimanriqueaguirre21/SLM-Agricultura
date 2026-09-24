from fastapi import APIRouter

from app.infrastructure.adapters.output.mysql.connection import ping_postgres
from app.infrastructure.composition import CompositionRoot


def create_health_router(container: CompositionRoot) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health")
    def health() -> dict[str, str]:
        postgres_status = "connected" if ping_postgres(container.settings) else "disconnected"
        return {
            "status": "ok",
            "service": container.settings.app_name,
            "phase": "1",
            "architecture": "hexagonal",
            "postgres": postgres_status,
        }

    return router
