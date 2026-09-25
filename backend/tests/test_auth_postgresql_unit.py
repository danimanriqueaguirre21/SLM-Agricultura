"""Pruebas aisladas: no construyen el contenedor real ni conectan a PostgreSQL."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.application.useCases.iniciar_sesion_agricultor import IniciarSesionAgricultor
from app.application.useCases.registrar_agricultor import RegistrarAgricultor
from app.domain.entities.agricultor import Agricultor
from app.domain.exceptions import (
    ErrorCorreoDuplicado,
    ErrorCorreoInvalido,
    ErrorCredencialesInvalidas,
)
from app.domain.ports.input.iniciar_sesion_agricultor_port import ComandoIniciarSesionAgricultor
from app.domain.ports.input.registrar_agricultor_port import ComandoRegistrarAgricultor
from app.domain.ports.output.repositorio_agricultor_port import (
    DatosAutenticacionAgricultor,
    PuertoRepositorioAgricultor,
)
from app.domain.valueObjects.email import Email
from app.domain.valueObjects.hash_contrasena import HashContrasena
from app.infrastructure.adapters.input.http.auth_controller import create_auth_router
from app.infrastructure.adapters.output.mysql.repositorio_agricultor import (
    RepositorioAgricultorPostgresql,
)
from app.infrastructure.adapters.output.security.emisor_token_jwt import EmisorTokenJwt
from app.infrastructure.adapters.output.security.hasher_contrasena_bcrypt import (
    HasherContrasenaBcrypt,
)

USER_ID = "5c5193a8-56d1-496f-8c73-bf1b5c430124"
FARMER_ID = "b3f66a93-fd93-49e4-a98f-cb35b836e414"
SECRET = "unit-test-secret-not-used-in-production"
PASSWORD = "Password123!"


def datos():
    return DatosAutenticacionAgricultor(
        id_usuario=USER_ID,
        id_agricultor=FARMER_ID,
        rol="AGRICULTOR",
        nombre="Juan Perez",
        email=Email("juan@example.com"),
        hash_contrasena=HashContrasena("$fake$hash"),
        estado="ACTIVO",
    )


def agricultor():
    return Agricultor.registrar(
        nombres="Juan", apellidos="Perez",
        email=Email("juan@example.com"),
        hash_contrasena=HashContrasena("$fake$hash"),
    )


def adapter():
    session = MagicMock()
    factory = Mock(return_value=session)
    session.__enter__.return_value = session
    return RepositorioAgricultorPostgresql(factory), session


def postgres_error(code, message="", constraint=None, table=None):
    original = Exception(message)
    original.sqlstate = code
    original.diag = SimpleNamespace(
        message_primary=message, constraint_name=constraint, table_name=table
    )
    return DBAPIError("unit-test statement", {}, original)


def login_case(account=None):
    repository = Mock(spec=PuertoRepositorioAgricultor)
    repository.buscar_por_correo.return_value = account or datos()
    hasher = Mock()
    hasher.verificar_contrasena.return_value = True
    issuer = Mock()
    issuer.emitir_token.return_value = "token"
    return IniciarSesionAgricultor(repository, hasher, issuer), repository, hasher, issuer


def command():
    return ComandoIniciarSesionAgricultor("juan@example.com", PASSWORD)


@pytest.mark.parametrize("changes", [
    {"estado": "INACTIVO"}, {"estado": "BLOQUEADO"},
    {"rol": "ADMINISTRADOR"}, {"id_agricultor": None},
])
def test_login_rejects_ineligible_accounts_without_access_or_token(changes):
    use_case, repository, hasher, issuer = login_case(replace(datos(), **changes))
    with pytest.raises(ErrorCredencialesInvalidas):
        use_case.ejecutar(command())
    repository.actualizar_ultimo_acceso.assert_not_called()
    hasher.verificar_contrasena.assert_not_called()
    issuer.emitir_token.assert_not_called()


def test_login_updates_user_before_issuing_farmer_token():
    use_case, repository, _, issuer = login_case()
    order = Mock()
    order.attach_mock(repository.actualizar_ultimo_acceso, "access")
    order.attach_mock(issuer.emitir_token, "token")
    result = use_case.ejecutar(command())
    repository.actualizar_ultimo_acceso.assert_called_once_with(USER_ID)
    issuer.emitir_token.assert_called_once_with(
        sujeto=FARMER_ID, claims={"email": "juan@example.com"}
    )
    assert [call[0] for call in order.mock_calls] == ["access", "token"]
    assert result.agricultor.id == FARMER_ID


def test_wrong_password_does_not_update_access():
    use_case, repository, hasher, issuer = login_case()
    hasher.verificar_contrasena.return_value = False
    with pytest.raises(ErrorCredencialesInvalidas):
        use_case.ejecutar(command())
    repository.actualizar_ultimo_acceso.assert_not_called()
    issuer.emitir_token.assert_not_called()


def test_failed_access_update_does_not_issue_token():
    use_case, repository, _, issuer = login_case()
    repository.actualizar_ultimo_acceso.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        use_case.ejecutar(command())
    issuer.emitir_token.assert_not_called()


def test_register_rejects_email_longer_than_database_column():
    repository = Mock(spec=PuertoRepositorioAgricultor)
    hasher = Mock()
    with pytest.raises(ErrorCorreoInvalido, match="150"):
        RegistrarAgricultor(repository, hasher).ejecutar(
            ComandoRegistrarAgricultor("Juan", "Perez", "a" * 140 + "@example.com", PASSWORD)
        )
    repository.existe_por_correo.assert_not_called()
    repository.guardar.assert_not_called()
    hasher.hashear_contrasena.assert_not_called()


def test_register_uses_routine_and_committed_farmer_uuid():
    repository, session = adapter()
    farmer = agricultor()
    old_id = farmer.id
    session.execute.return_value.mappings.return_value.one.return_value = {
        "id_usuario": UUID(USER_ID), "id_agricultor": UUID(FARMER_ID),
    }

    def on_transaction_exit(*args):
        assert farmer.id == old_id
        return False

    session.begin.return_value.__exit__.side_effect = on_transaction_exit
    repository.guardar(farmer)
    sql, params = session.execute.call_args.args
    assert str(sql) == (
        "SELECT * FROM sp_registrar_agricultor("
        "p_nombre => :nombre, p_email => :email, p_password_hash => :password_hash)"
    )
    assert params == {
        "nombre": "Juan Perez", "email": "juan@example.com", "password_hash": "$fake$hash"
    }
    assert farmer.id == FARMER_ID
    session.begin.return_value.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("failure_at_commit", [False, True])
def test_register_preserves_id_when_transaction_fails(failure_at_commit):
    repository, session = adapter()
    farmer = agricultor()
    old_id = farmer.id
    error = postgres_error("08006", "connection lost")
    session.execute.return_value.mappings.return_value.one.return_value = {
        "id_usuario": UUID(USER_ID), "id_agricultor": UUID(FARMER_ID),
    }
    if failure_at_commit:
        session.begin.return_value.__exit__.side_effect = error
    else:
        session.execute.side_effect = error
    with pytest.raises(DBAPIError) as caught:
        repository.guardar(farmer)
    assert caught.value is error
    assert farmer.id == old_id
    session.begin.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("code,message,constraint,table,duplicate", [
    ("P0001", "Ya existe un usuario registrado con ese correo", None, None, True),
    ("23505", "", "usuario_email_key", "usuario", True),
    ("P0001", "El nombre es obligatorio", None, None, False),
    ("23505", "", "rol_nombre_key", "rol", False),
    ("23503", "", "fk_usuario_rol", "usuario", False),
    ("08006", "connection lost", None, None, False),
])
def test_only_email_conflicts_are_translated(code, message, constraint, table, duplicate):
    repository, session = adapter()
    error = postgres_error(code, message, constraint, table)
    session.execute.side_effect = error
    with pytest.raises(ErrorCorreoDuplicado if duplicate else DBAPIError) as caught:
        repository.guardar(agricultor())
    if duplicate:
        assert caught.value.__cause__ is error
    else:
        assert caught.value is error
    assert session.begin.return_value.__exit__.call_args.args[1] is error


@pytest.mark.parametrize("farmer_id", [UUID(FARMER_ID), None])
def test_login_routine_maps_uuid_and_optional_profile(farmer_id):
    repository, session = adapter()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "id_usuario": UUID(USER_ID), "id_agricultor": farmer_id,
        "id_rol": 1, "rol": "AGRICULTOR", "nombre": "Juan Perez",
        "email": "juan@example.com", "password_hash": "$fake$hash", "estado": "ACTIVO",
    }
    result = repository.buscar_por_correo(Email(" JUAN@example.com "))
    sql, params = session.execute.call_args.args
    assert str(sql) == "SELECT * FROM sp_obtener_usuario_login(p_email => :email)"
    assert params == {"email": "juan@example.com"}
    assert result.id_usuario == USER_ID
    assert result.id_agricultor == (FARMER_ID if farmer_id else None)
    assert result.hash_contrasena.value == "$fake$hash"
    assert result.estado == "ACTIVO"
    assert result.rol == "AGRICULTOR"


def test_unknown_login_returns_none():
    repository, session = adapter()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = None
    assert repository.buscar_por_correo(Email("missing@example.com")) is None


def test_email_lookup_checks_usuario_without_role_filter():
    repository, session = adapter()
    session.scalar.return_value = True
    assert repository.existe_por_correo(Email(" JUAN@example.com "))
    sql, params = session.scalar.call_args.args
    assert str(sql) == "SELECT EXISTS (SELECT 1 FROM usuario WHERE LOWER(email) = :email)"
    assert params == {"email": "juan@example.com"}


def test_access_procedure_uses_user_uuid_and_transaction():
    repository, session = adapter()
    repository.actualizar_ultimo_acceso(USER_ID)
    sql, params = session.execute.call_args.args
    assert str(sql) == (
        "CALL sp_actualizar_ultimo_acceso(p_id_usuario => CAST(:id_usuario AS UUID))"
    )
    assert params == {"id_usuario": USER_ID}
    session.begin.return_value.__exit__.assert_called_once_with(None, None, None)


def test_http_contract_with_real_bcrypt_and_jwt_without_database():
    repository = Mock(spec=PuertoRepositorioAgricultor)
    repository.existe_por_correo.return_value = False
    stored = []

    def save(farmer):
        farmer.id = FARMER_ID
        stored.append(farmer)

    repository.guardar.side_effect = save
    hasher = HasherContrasenaBcrypt()
    container = SimpleNamespace(
        puerto_registrar_agricultor=RegistrarAgricultor(repository, hasher),
        puerto_iniciar_sesion_agricultor=IniciarSesionAgricultor(
            repository, hasher, EmisorTokenJwt(SECRET, "HS256", 120)
        ),
    )
    app = FastAPI()
    app.include_router(create_auth_router(container))
    with TestClient(app) as client:
        register = client.post("/api/v1/auth/register", json={
            "names": "Juan", "last_names": "Perez",
            "email": " JUAN@example.com ", "password": PASSWORD,
        })
        expected = {
            "id": FARMER_ID, "names": "Juan", "last_names": "Perez",
            "email": "juan@example.com",
        }
        assert register.status_code == 201
        assert register.json() == expected
        hashed = stored[0].hash_contrasena.value
        assert hashed.startswith("$2")
        assert hasher.verificar_contrasena(PASSWORD, hashed)
        repository.buscar_por_correo.return_value = replace(
            datos(), hash_contrasena=HashContrasena(hashed)
        )
        login = client.post("/api/v1/auth/login", json={
            "email": "juan@example.com", "password": PASSWORD,
        })
        assert login.status_code == 200
        body = login.json()
        assert set(body) == {"access_token", "token_type", "farmer"}
        assert body["farmer"] == expected
        assert body["token_type"] == "bearer"
        claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
        assert claims["sub"] == FARMER_ID
        assert claims["sub"] != USER_ID
        assert claims["email"] == expected["email"]
        assert "exp" in claims
        repository.actualizar_ultimo_acceso.assert_called_once_with(USER_ID)
        assert hashed not in login.text
