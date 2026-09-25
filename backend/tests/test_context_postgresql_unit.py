"""Contextos aislados: no importan app.main ni conectan a PostgreSQL."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.application.useCases.crear_contexto_agricola import CrearContextoAgricola
from app.application.useCases.listar_contextos_agricolas import ListarContextosAgricolas
from app.application.useCases.seleccionar_contexto_agricola import SeleccionarContextoAgricola
from app.domain.entities.contexto_agricola import ContextoAgricola
from app.domain.exceptions import ErrorContextoNoEncontrado, ErrorDatosContextoInvalidos
from app.domain.valueObjects.cultivo import Cultivo
from app.domain.valueObjects.region import Region
from app.infrastructure.adapters.input.http.context_controller import create_context_router
from app.infrastructure.adapters.output.mysql.repositorio_contexto_agricola_postgresql import (
    RepositorioContextoAgricolaPostgresql,
)
from app.infrastructure.adapters.output.security.verificador_token_jwt import VerificadorTokenJwt
from test_agricultural_context import RepositorioContextoEnMemoria, FARMER_A, FARMER_B

CONTEXT_ID = str(uuid4())
PLOT_ID = str(uuid4())
CREATED = datetime(2026, 9, 24, 10, 30, tzinfo=timezone.utc)
SECRET = "isolated-context-tests-secret-32-characters"


def row(selected=False):
    return dict(id_cultivo=UUID(CONTEXT_ID), nombre_comun="papa", parcela="Parcela 1",
                ubicacion="Huancayo", observaciones="Riego", fecha_creacion=CREATED,
                esta_seleccionado=selected)


def adapter():
    session = MagicMock()
    session.__enter__.return_value = session
    factory = Mock(return_value=session)
    return RepositorioContextoAgricolaPostgresql(factory), session, factory


def context():
    return ContextoAgricola.crear(FARMER_A, "Parcela 1", Cultivo("papa"), Region("Huancayo"), "Riego")


def db_error(code, message):
    original = Exception(message)
    original.sqlstate = code
    original.diag = SimpleNamespace(message_primary=message)
    return DBAPIError("test", {}, original)


def test_create_uses_one_transaction_and_persisted_context():
    repo, session, factory = adapter()
    session.scalar.side_effect = [UUID(PLOT_ID), UUID(CONTEXT_ID)]
    session.execute.return_value.mappings.return_value.one_or_none.return_value = row()
    item = context()
    old_id = item.id

    def commit(*args):
        assert item.id == old_id
        return False

    session.begin.return_value.__exit__.side_effect = commit
    repo.guardar(item)
    factory.assert_called_once()
    session.begin.assert_called_once()
    session.begin.return_value.__exit__.assert_called_once_with(None, None, None)
    first, second = session.scalar.call_args_list
    assert "sp_registrar_parcela" in str(first.args[0])
    assert first.args[1] == {"agricultor_id": FARMER_A, "nombre": "Parcela 1", "ubicacion": "Huancayo"}
    assert "sp_registrar_cultivo" in str(second.args[0])
    assert second.args[1] == {"parcela_id": PLOT_ID, "cultivo": "papa", "notas": "Riego"}
    assert "sp_obtener_contexto_cultivo" in str(session.execute.call_args.args[0])
    assert session.execute.call_args.args[1] == {"agricultor_id": FARMER_A, "contexto_id": CONTEXT_ID}
    assert item.id == CONTEXT_ID
    assert item.creado_en == CREATED
    assert item.esta_seleccionado is False


@pytest.mark.parametrize("stage", ["cultivo", "detalle", "commit"])
def test_create_failure_exits_transaction_with_error_and_preserves_entity(stage):
    repo, session, _ = adapter()
    error = db_error("08006", "connection lost")
    session.scalar.side_effect = [UUID(PLOT_ID), error if stage == "cultivo" else UUID(CONTEXT_ID)]
    session.execute.return_value.mappings.return_value.one_or_none.return_value = row()
    if stage == "detalle":
        session.execute.side_effect = error
    if stage == "commit":
        session.begin.return_value.__exit__.side_effect = error
    item = context()
    before = item.__dict__.copy()
    with pytest.raises(DBAPIError) as caught:
        repo.guardar(item)
    assert caught.value is error
    assert item.__dict__ == before
    session.begin.return_value.__exit__.assert_called_once()
    if stage != "commit":
        assert session.begin.return_value.__exit__.call_args.args[1] is error
    session.commit.assert_not_called()  # Solo el contexto transaccional confirma.


def test_list_calls_routine_with_authenticated_uuid_and_maps_optional_fields():
    repo, session, _ = adapter()
    record = row(True)
    record.update(parcela=None, observaciones=None)
    session.execute.return_value.mappings.return_value.all.return_value = [record]
    result = repo.listar_por_agricultor(FARMER_B)
    assert "sp_listar_cultivos_agricultor" in str(session.execute.call_args.args[0])
    assert session.execute.call_args.args[1] == {"agricultor_id": FARMER_B}
    assert result[0].agricultor_id == FARMER_B
    assert result[0].id == CONTEXT_ID
    assert result[0].nombre_predio is None
    assert result[0].observaciones is None
    assert result[0].esta_seleccionado is True
    assert result[0].creado_en == CREATED


def test_empty_list():
    repo, session, _ = adapter()
    session.execute.return_value.mappings.return_value.all.return_value = []
    assert repo.listar_por_agricultor(FARMER_A) == []


def test_select_uses_routine_and_reads_detail_in_same_transaction():
    repo, session, factory = adapter()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = row(True)
    result = repo.seleccionar_para_agricultor(CONTEXT_ID, FARMER_A)
    factory.assert_called_once()
    assert "sp_seleccionar_cultivo" in str(session.scalar.call_args.args[0])
    assert session.scalar.call_args.args[1] == {"agricultor_id": FARMER_A, "contexto_id": CONTEXT_ID}
    assert result.id == CONTEXT_ID and result.esta_seleccionado
    session.begin.return_value.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize("code,message,missing", [
    ("P0002", "Cultivo no encontrado para el agricultor", True),
    ("P0002", "Otro error", False),
    ("23503", "Foreign key violation", False),
    ("08006", "Connection lost", False),
])
def test_select_translates_only_expected_not_found(code, message, missing):
    repo, session, _ = adapter()
    error = db_error(code, message)
    session.scalar.side_effect = error
    if missing:
        assert repo.seleccionar_para_agricultor(CONTEXT_ID, FARMER_A) is None
    else:
        with pytest.raises(DBAPIError) as caught:
            repo.seleccionar_para_agricultor(CONTEXT_ID, FARMER_A)
        assert caught.value is error
    assert session.begin.return_value.__exit__.call_args.args[1] is error
    session.execute.assert_not_called()


def test_invalid_uuids_rejected_before_opening_session():
    repo, _, factory = adapter()
    with pytest.raises(ErrorDatosContextoInvalidos):
        repo.listar_por_agricultor("123")
    with pytest.raises(ErrorContextoNoEncontrado):
        repo.seleccionar_para_agricultor("123", FARMER_A)
    with pytest.raises(ErrorDatosContextoInvalidos):
        repo.seleccionar_para_agricultor(CONTEXT_ID, "farmer-a")
    factory.assert_not_called()


def headers(farmer):
    return {"Authorization": "Bearer " + jwt.encode({"sub": farmer}, SECRET, algorithm="HS256")}


@pytest.fixture
def client():
    repo = RepositorioContextoEnMemoria()
    container = SimpleNamespace(
        puerto_verificador_token=VerificadorTokenJwt(SECRET, "HS256"),
        puerto_crear_contexto_agricola=CrearContextoAgricola(repo),
        puerto_listar_contextos_agricolas=ListarContextosAgricolas(repo),
        puerto_seleccionar_contexto_agricola=SeleccionarContextoAgricola(repo),
    )
    app = FastAPI()
    app.include_router(create_context_router(container))
    with TestClient(app) as http:
        yield http


def test_http_contract_selection_and_isolation(client):
    payload = {"plot_name": "Parcela 1", "crop": "papa", "region": "Huancayo", "notes": "Riego"}
    records = {}
    for farmer in (FARMER_A, FARMER_B):
        response = client.post("/api/v1/contexts", json={**payload, "farmer_id": str(uuid4())}, headers=headers(farmer))
        assert response.status_code == 201
        body = response.json()
        assert set(body) == {"id", "farmer_id", "plot_name", "crop", "region", "notes", "is_selected", "created_at"}
        assert str(UUID(body["id"])) == body["id"]
        assert body["farmer_id"] == farmer
        assert {key: body[key] for key in payload} == payload
        assert body["is_selected"] is False
        datetime.fromisoformat(body["created_at"])
        records[farmer] = body
    for farmer, other in ((FARMER_A, FARMER_B), (FARMER_B, FARMER_A)):
        listed = client.get("/api/v1/contexts", headers=headers(farmer))
        assert listed.status_code == 200
        assert listed.json() == [records[farmer]]
        denied = client.post(f"/api/v1/contexts/{records[other]['id']}/select", headers=headers(farmer))
        assert denied.status_code == 404
        selected = client.post(f"/api/v1/contexts/{records[farmer]['id']}/select", headers=headers(farmer))
        assert selected.status_code == 200
        assert selected.json() == {**records[farmer], "is_selected": True}


def test_http_bad_ids_and_auth(client):
    assert client.get("/api/v1/contexts").status_code == 401
    assert client.get("/api/v1/contexts", headers=headers("123")).status_code == 401
    assert client.post("/api/v1/contexts/not-a-uuid/select", headers=headers(FARMER_A)).status_code == 422
    assert client.post(f"/api/v1/contexts/{uuid4()}/select", headers=headers(FARMER_A)).status_code == 404


def test_legacy_query_model_import_remains_available():
    from app.infrastructure.adapters.output.mysql.repositorio_consulta import RegistroContextoAgricola
    assert RegistroContextoAgricola.__tablename__ == "contextos_agricolas"


def test_context_openapi_declares_bearer_for_all_three_operations(client):
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http", "scheme": "bearer",
    }
    for path, method in (
        ("/api/v1/contexts", "post"),
        ("/api/v1/contexts", "get"),
        ("/api/v1/contexts/{context_id}/select", "post"),
    ):
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"HTTPBearer": []}]
        assert not any(
            parameter["name"].lower() == "authorization"
            for parameter in operation.get("parameters", [])
        )


@pytest.mark.parametrize("authorization", [None, "", "Bearer", "Bearer   ", "Basic abc", "Bearer invalid-jwt"])
@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/contexts"),
    ("post", "/api/v1/contexts"),
    ("post", f"/api/v1/contexts/{CONTEXT_ID}/select"),
])
def test_context_auth_preserves_401_response(client, authorization, method, path):
    response = client.request(
        method, path,
        headers={} if authorization is None else {"Authorization": authorization},
        json={"crop": "papa", "region": "Huancayo"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "No autenticado"}
