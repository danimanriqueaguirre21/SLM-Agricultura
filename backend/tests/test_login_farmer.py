from pathlib import Path

import pytest

from app.application.useCases.iniciar_sesion_agricultor import IniciarSesionAgricultor
from app.domain.entities.agricultor import Agricultor
from app.domain.exceptions import ErrorCorreoInvalido, ErrorCredencialesInvalidas
from app.domain.ports.input.iniciar_sesion_agricultor_port import ComandoIniciarSesionAgricultor
from app.domain.ports.output.hasher_contrasena_port import PuertoHasherContrasena
from app.domain.ports.output.repositorio_agricultor_port import (
    DatosAutenticacionAgricultor,
    PuertoRepositorioAgricultor,
)
from app.domain.ports.output.token_issuer_port import PuertoEmisorToken
from app.domain.valueObjects.email import Email
from app.domain.valueObjects.hash_contrasena import HashContrasena


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
    def __init__(self) -> None:
        self.verify_calls: list[tuple[str, str]] = []

    def hashear_contrasena(self, contrasena: str) -> str:
        return f"$fake${contrasena}"

    def verificar_contrasena(self, contrasena: str, hash_contrasena: str) -> bool:
        self.verify_calls.append((contrasena, hash_contrasena))
        return hash_contrasena == f"$fake${contrasena}"


class EmisorTokenFalso(PuertoEmisorToken):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def emitir_token(self, sujeto: str, claims: dict[str, str]) -> str:
        self.calls.append((sujeto, claims))
        return f"token-for-{sujeto}"


def _registered_use_case(
    password: str = "Password123!",
) -> tuple[IniciarSesionAgricultor, Agricultor, HasherContrasenaFalso, EmisorTokenFalso]:
    repository = RepositorioAgricultorEnMemoria()
    hasher = HasherContrasenaFalso()
    tokens = EmisorTokenFalso()
    agricultor = Agricultor.registrar(
        nombres="Juan",
        apellidos="Pérez",
        email=Email("juan@example.com"),
        hash_contrasena=HashContrasena(hasher.hashear_contrasena(password)),
    )
    repository.guardar(agricultor)
    return IniciarSesionAgricultor(repository, hasher, tokens), agricultor, hasher, tokens


def test_login_farmer_success() -> None:
    use_case, farmer, hasher, tokens = _registered_use_case()

    result = use_case.ejecutar(
        ComandoIniciarSesionAgricultor(email="juan@example.com", contrasena="Password123!")
    )

    assert result.access_token == f"token-for-{farmer.id}"
    assert result.token_type == "bearer"
    assert result.agricultor.id == farmer.id
    assert result.agricultor.email == "juan@example.com"
    assert result.agricultor.nombres == "Juan"
    assert "password" not in result.__dict__
    assert not hasattr(result.agricultor, "hash_contrasena")
    assert hasher.verify_calls == [("Password123!", farmer.hash_contrasena.value)]
    assert tokens.calls == [(farmer.id, {"email": "juan@example.com"})]


def test_login_unknown_email_returns_generic_error() -> None:
    use_case, _farmer, hasher, tokens = _registered_use_case()

    with pytest.raises(ErrorCredencialesInvalidas, match="Credenciales inválidas"):
        use_case.ejecutar(
            ComandoIniciarSesionAgricultor(email="otro@example.com", contrasena="Password123!")
        )
    assert hasher.verify_calls == []
    assert tokens.calls == []


def test_login_wrong_password_returns_generic_error() -> None:
    use_case, _farmer, hasher, tokens = _registered_use_case()

    with pytest.raises(ErrorCredencialesInvalidas, match="Credenciales inválidas"):
        use_case.ejecutar(
            ComandoIniciarSesionAgricultor(email="juan@example.com", contrasena="WrongPass1")
        )
    assert len(hasher.verify_calls) == 1
    assert tokens.calls == []


def test_login_invalid_email() -> None:
    use_case, _farmer, _hasher, _tokens = _registered_use_case()
    with pytest.raises(ErrorCorreoInvalido):
        use_case.ejecutar(
            ComandoIniciarSesionAgricultor(email="no-es-correo", contrasena="Password123!")
        )


def test_login_result_does_not_leak_password_hash() -> None:
    use_case, _farmer, _hasher, _tokens = _registered_use_case()
    result = use_case.ejecutar(
        ComandoIniciarSesionAgricultor(email="juan@example.com", contrasena="Password123!")
    )
    dumped = str(result)
    assert "password_hash" not in dumped
    assert "$fake$" not in dumped


def test_login_use_case_depends_on_ports_not_libraries() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "application"
        / "useCases"
        / "iniciar_sesion_agricultor.py"
    ).read_text(encoding="utf-8").lower()
    assert "puertorepositorioagricultor" in source
    assert "puertohashercontrasena" in source
    assert "puertoemisortoken" in source
    assert "import jwt" not in source
    assert "from jwt" not in source
    assert "import bcrypt" not in source
    assert "from bcrypt" not in source
    assert "fastapi" not in source
    assert "sqlalchemy" not in source
    assert "pydantic" not in source
    assert "emisortokenjwt" not in source
    assert "hashercontrasenabcrypt" not in source
