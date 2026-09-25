from pathlib import Path

import pytest

from app.application.useCases.crear_contexto_agricola import CrearContextoAgricola
from app.application.useCases.listar_contextos_agricolas import ListarContextosAgricolas
from app.application.useCases.seleccionar_contexto_agricola import SeleccionarContextoAgricola
from app.domain.entities.contexto_agricola import ContextoAgricola
from app.domain.exceptions import ErrorContextoNoEncontrado, ErrorDatosContextoInvalidos
from app.domain.ports.input.gestionar_contexto_port import (
    ComandoCrearContextoAgricola,
    ComandoSeleccionarContextoAgricola,
)
from app.domain.ports.output.repositorio_contexto_agricola_port import (
    PuertoRepositorioContextoAgricola,
)


class RepositorioContextoEnMemoria(PuertoRepositorioContextoAgricola):
    def __init__(self) -> None:
        self.contextos: list[ContextoAgricola] = []

    def guardar(self, contexto: ContextoAgricola) -> None:
        self.contextos.append(contexto)

    def listar_por_agricultor(self, agricultor_id: str) -> list[ContextoAgricola]:
        return [contexto for contexto in self.contextos if contexto.agricultor_id == agricultor_id]

    def buscar_por_id_para_agricultor(
        self, contexto_id: str, agricultor_id: str
    ) -> ContextoAgricola | None:
        for contexto in self.contextos:
            if contexto.id == contexto_id and contexto.agricultor_id == agricultor_id:
                return contexto
        return None

    def seleccionar_para_agricultor(
        self, contexto_id: str, agricultor_id: str
    ) -> ContextoAgricola | None:
        objetivo = self.buscar_por_id_para_agricultor(contexto_id, agricultor_id)
        if objetivo is None:
            return None
        for contexto in self.contextos:
            if contexto.agricultor_id == agricultor_id:
                contexto.marcar_no_seleccionado()
        objetivo.marcar_seleccionado()
        return objetivo


FARMER_A = "6ffb54e1-6e78-4eb3-b9ed-5db6b6786faa"
FARMER_B = "628bfb8f-deed-48a6-b9bb-dff4ca9410e1"


def _create(
    repository: RepositorioContextoEnMemoria,
    farmer_id: str = FARMER_A,
    crop: str = "papa",
    region: str = "Huancayo",
) -> str:
    use_case = CrearContextoAgricola(repository)
    result = use_case.ejecutar(
        ComandoCrearContextoAgricola(
            agricultor_id=farmer_id,
            nombre_predio="Parcela 1",
            cultivo=crop,
            region=region,
            observaciones="Riego por gravedad",
        )
    )
    return result.id


def test_create_agricultural_context() -> None:
    repository = RepositorioContextoEnMemoria()
    result = CrearContextoAgricola(repository).ejecutar(
        ComandoCrearContextoAgricola(
            agricultor_id=FARMER_A,
            nombre_predio="Parcela 1",
            cultivo="papa",
            region="Huancayo",
            observaciones=None,
        )
    )
    assert result.agricultor_id == FARMER_A
    assert result.cultivo == "papa"
    assert result.region == "Huancayo"
    assert result.esta_seleccionado is False
    assert len(repository.contextos) == 1


def test_list_contexts_only_returns_authenticated_farmer() -> None:
    repository = RepositorioContextoEnMemoria()
    _create(repository, FARMER_A, crop="papa")
    _create(repository, FARMER_B, crop="maiz")

    listed = ListarContextosAgricolas(repository).ejecutar(FARMER_A)
    assert len(listed) == 1
    assert listed[0].cultivo == "papa"
    assert all(item.agricultor_id == FARMER_A for item in listed)


def test_select_own_context() -> None:
    repository = RepositorioContextoEnMemoria()
    first = _create(repository, FARMER_A, crop="papa")
    second = _create(repository, FARMER_A, crop="maiz")

    selected = SeleccionarContextoAgricola(repository).ejecutar(
        ComandoSeleccionarContextoAgricola(agricultor_id=FARMER_A, contexto_id=second)
    )
    assert selected.id == second
    assert selected.esta_seleccionado is True
    stored_first = repository.buscar_por_id_para_agricultor(first, FARMER_A)
    stored_second = repository.buscar_por_id_para_agricultor(second, FARMER_A)
    assert stored_first is not None and stored_first.esta_seleccionado is False
    assert stored_second is not None and stored_second.esta_seleccionado is True


def test_cannot_select_another_farmer_context() -> None:
    repository = RepositorioContextoEnMemoria()
    context_b = _create(repository, FARMER_B, crop="maiz")
    with pytest.raises(ErrorContextoNoEncontrado):
        SeleccionarContextoAgricola(repository).ejecutar(
            ComandoSeleccionarContextoAgricola(agricultor_id=FARMER_A, contexto_id=context_b)
        )


def test_create_requires_crop() -> None:
    repository = RepositorioContextoEnMemoria()
    with pytest.raises(ErrorDatosContextoInvalidos, match="cultivo"):
        CrearContextoAgricola(repository).ejecutar(
            ComandoCrearContextoAgricola(
                agricultor_id=FARMER_A,
                nombre_predio=None,
                cultivo="  ",
                region="Huancayo",
                observaciones=None,
            )
        )


def test_context_use_cases_do_not_import_frameworks() -> None:
    use_cases = Path(__file__).resolve().parents[1] / "app" / "application" / "useCases"
    forbidden = ("fastapi", "sqlalchemy", "import jwt", "from jwt", "import bcrypt")
    for name in (
        "crear_contexto_agricola.py",
        "listar_contextos_agricolas.py",
        "seleccionar_contexto_agricola.py",
    ):
        source = (use_cases / name).read_text(encoding="utf-8").lower()
        for item in forbidden:
            assert item not in source
