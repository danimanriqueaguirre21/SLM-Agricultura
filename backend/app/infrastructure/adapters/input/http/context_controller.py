from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.domain.exceptions import (
    ErrorContextoNoEncontrado,
    ErrorDatosContextoInvalidos,
    ErrorDominio,
    ErrorTokenInvalido,
)
from app.domain.ports.input.gestionar_contexto_port import (
    ComandoCrearContextoAgricola,
    ComandoSeleccionarContextoAgricola,
    ResultadoContextoAgricola,
)
from app.infrastructure.composition import CompositionRoot


class CreateContextRequest(BaseModel):
    plot_name: str | None = None
    crop: str = Field(min_length=1)
    region: str = Field(min_length=1)
    notes: str | None = None


class AgriculturalContextResponse(BaseModel):
    id: str
    farmer_id: str
    plot_name: str | None
    crop: str
    region: str
    notes: str | None
    is_selected: bool
    created_at: str


def _context_response(resultado: ResultadoContextoAgricola) -> AgriculturalContextResponse:
    return AgriculturalContextResponse(
        id=resultado.id,
        farmer_id=resultado.agricultor_id,
        plot_name=resultado.nombre_predio,
        crop=resultado.cultivo,
        region=resultado.region,
        notes=resultado.observaciones,
        is_selected=resultado.esta_seleccionado,
        created_at=resultado.creado_en,
    )


def create_context_router(container: CompositionRoot) -> APIRouter:
    router = APIRouter(prefix="/api/v1/contexts", tags=["contexts"])
    bearer = HTTPBearer(auto_error=False)

    def current_farmer_id(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> str:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No autenticado",
            )
        token = credentials.credentials.strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No autenticado",
            )
        try:
            identity = container.puerto_verificador_token.verificar(token)
        except ErrorTokenInvalido as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(error),
            ) from error
        try:
            return str(UUID(identity.agricultor_id))
        except (ValueError, TypeError, AttributeError) as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No autenticado",
            ) from error

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=AgriculturalContextResponse,
    )
    def create_context(
        payload: CreateContextRequest,
        farmer_id: str = Depends(current_farmer_id),
    ) -> AgriculturalContextResponse:
        command = ComandoCrearContextoAgricola(
            agricultor_id=farmer_id,
            nombre_predio=payload.plot_name,
            cultivo=payload.crop,
            region=payload.region,
            observaciones=payload.notes,
        )
        try:
            result = container.puerto_crear_contexto_agricola.ejecutar(command)
        except ErrorDatosContextoInvalidos as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except ErrorDominio as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        return _context_response(result)

    @router.get("", response_model=list[AgriculturalContextResponse])
    def list_contexts(
        farmer_id: str = Depends(current_farmer_id),
    ) -> list[AgriculturalContextResponse]:
        results = container.puerto_listar_contextos_agricolas.ejecutar(farmer_id)
        return [_context_response(item) for item in results]

    @router.post(
        "/{context_id}/select",
        response_model=AgriculturalContextResponse,
    )
    def select_context(
        context_id: UUID,
        farmer_id: str = Depends(current_farmer_id),
    ) -> AgriculturalContextResponse:
        command = ComandoSeleccionarContextoAgricola(
            agricultor_id=farmer_id,
            contexto_id=str(context_id),
        )
        try:
            result = container.puerto_seleccionar_contexto_agricola.ejecutar(command)
        except ErrorContextoNoEncontrado as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except ErrorDominio as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        return _context_response(result)

    return router
