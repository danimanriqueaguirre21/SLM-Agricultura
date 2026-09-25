from pathlib import Path

import pytest

from app.application.useCases.registrar_agricultor import RegistrarAgricultor
from app.domain.entities.agricultor import Agricultor
from app.domain.exceptions import (
    ErrorContrasenaInvalida,
    ErrorCorreoDuplicado,
    ErrorCorreoInvalido,
    ErrorDatosAgricultorInvalidos,
)
from app.domain.ports.input.registrar_agricultor_port import ComandoRegistrarAgricultor
from app.domain.ports.output.hasher_contrasena_port import PuertoHasherContrasena
from app.domain.ports.output.repositorio_agricultor_port import (
    DatosAutenticacionAgricultor,
    PuertoRepositorioAgricultor,
)
from app.domain.valueObjects.email import Email


class RepositorioAgricultorEnMemoria(PuertoRepositorioAgricultor):
    def __init__(self) -> None:
        self.agricultores: list[Agricultor] = []
        self.accesos: list[str] = []

    def existe_por_correo(self, email: Email) -> bool:
        return any(agricultor.email == email for agricultor in self.agricultores)

    def buscar_por_correo(self, email: Email) -> DatosAutenticacionAgricultor | None:
        for agricultor in self.agricultores:
            if agricultor.email == email:
                return DatosAutenticacionAgricultor(
                    id_usuario="5c5193a8-56d1-496f-8c73-bf1b5c430124",
                    id_agricultor=agricultor.id,
                    rol="AGRICULTOR",
                    nombre=agricultor.nombre_completo,
                    email=agricultor.email,
                    hash_contrasena=agricultor.hash_contrasena,
                    estado="ACTIVO",
                )
        return None

    def actualizar_ultimo_acceso(self, id_usuario: str) -> None:
        self.accesos.append(id_usuario)

    def guardar(self, agricultor: Agricultor) -> None:
        self.agricultores.append(agricultor)


class HasherContrasenaFalso(PuertoHasherContrasena):
    def hashear_contrasena(self, contrasena: str) -> str:
        return f"$fake${contrasena}"

    def verificar_contrasena(self, contrasena: str, hash_contrasena: str) -> bool:
        return hash_contrasena == f"$fake${contrasena}"


def _caso_de_uso() -> tuple[RegistrarAgricultor, RepositorioAgricultorEnMemoria]:
    repositorio = RepositorioAgricultorEnMemoria()
    return RegistrarAgricultor(repositorio, HasherContrasenaFalso()), repositorio


def test_register_farmer_success() -> None:
    use_case, repository = _caso_de_uso()

    result = use_case.ejecutar(
        ComandoRegistrarAgricultor(
            nombres="Juan",
            apellidos="Pérez",
            email="juan@example.com",
            contrasena="Password123!",
        )
    )

    assert result.nombres == "Juan"
    assert result.apellidos == "Pérez"
    assert result.email == "juan@example.com"
    assert result.id
    assert len(repository.agricultores) == 1
    stored = repository.agricultores[0]
    assert stored.hash_contrasena.value == "$fake$Password123!"
    assert stored.hash_contrasena.value != "Password123!"


def test_register_farmer_duplicate_email() -> None:
    use_case, _repository = _caso_de_uso()
    command = ComandoRegistrarAgricultor(
        nombres="Juan",
        apellidos="Pérez",
        email="juan@example.com",
        contrasena="Password123!",
    )
    use_case.ejecutar(command)

    with pytest.raises(ErrorCorreoDuplicado, match="ya está registrado"):
        use_case.ejecutar(command)


def test_register_farmer_invalid_email() -> None:
    use_case, _repository = _caso_de_uso()
    with pytest.raises(ErrorCorreoInvalido):
        use_case.ejecutar(
            ComandoRegistrarAgricultor(
                nombres="Juan",
                apellidos="Pérez",
                email="correo-invalido",
                contrasena="Password123!",
            )
        )


def test_register_farmer_short_password() -> None:
    use_case, _repository = _caso_de_uso()
    with pytest.raises(ErrorContrasenaInvalida, match="8 caracteres"):
        use_case.ejecutar(
            ComandoRegistrarAgricultor(
                nombres="Juan",
                apellidos="Pérez",
                email="juan@example.com",
                contrasena="123",
            )
        )


def test_register_farmer_requires_names() -> None:
    use_case, _repository = _caso_de_uso()
    with pytest.raises(ErrorDatosAgricultorInvalidos, match="nombres"):
        use_case.ejecutar(
            ComandoRegistrarAgricultor(
                nombres="  ",
                apellidos="Pérez",
                email="juan@example.com",
                contrasena="Password123!",
            )
        )


def test_use_case_file_depends_on_ports_not_adapters() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "application"
        / "useCases"
        / "registrar_agricultor.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "puertorepositorioagricultor" in lowered
    assert "puertohashercontrasena" in lowered
    assert "repositorioagricultormysql" not in lowered
    assert "hashercontrasenabcrypt" not in lowered
    assert "fastapi" not in lowered
    assert "sqlalchemy" not in lowered
    assert "pydantic" not in lowered
    assert "import bcrypt" not in lowered
