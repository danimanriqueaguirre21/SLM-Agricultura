"""Contrato HTTP aislado: nunca importa app.main ni abre servicios reales."""
from types import SimpleNamespace
from uuid import UUID
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.services.fragmentador_documentos import FragmentadorDocumentos
from app.application.useCases.incorporar_conocimiento import IncorporarConocimiento
from app.application.useCases.indexar_conocimiento import IndexarConocimiento
from app.application.useCases.listar_documentos_conocimiento import ListarDocumentosConocimiento
from app.domain.exceptions import ErrorTokenInvalido
from app.infrastructure.adapters.input.http.knowledge_controller import create_knowledge_router
from app.infrastructure.adapters.input.http.context_controller import create_context_router
from app.infrastructure.adapters.output.security.verificador_token_jwt import VerificadorTokenJwt
from app.infrastructure.adapters.output.embedding.local_lexical_embedding_adapter import LocalLexicalEmbeddingAdapter
from test_index_knowledge import RepositorioConocimientoEnMemoria, AlmacenVectoresEnMemoria


@pytest.fixture
def client():
    repo = RepositorioConocimientoEnMemoria()
    store = AlmacenVectoresEnMemoria()
    def verificar(token):
        if token != "test-token":
            raise ErrorTokenInvalido("Token inválido")
        return SimpleNamespace(agricultor_id="d5d2d7b5-471e-4e62-8f31-a627a12da725")
    container = SimpleNamespace(
        puerto_verificador_token=SimpleNamespace(verificar=verificar),
        puerto_incorporar_conocimiento=IncorporarConocimiento(repo),
        puerto_listar_documentos_conocimiento=ListarDocumentosConocimiento(repo),
        puerto_indexar_conocimiento=IndexarConocimiento(repo, LocalLexicalEmbeddingAdapter(16), store, FragmentadorDocumentos(80)),
        settings=SimpleNamespace(chroma_collection="test-collection"),
    )
    app = FastAPI()
    app.include_router(create_knowledge_router(container))
    with TestClient(app) as test_client:
        yield test_client


AUTH = {"Authorization": "Bearer test-token"}
PAYLOAD = {"title": "Documento aprobado de prueba", "topic": "papa", "content": "Texto de prueba explícita.", "fuente": "Material de prueba local"}
INGEST = "/api/v1/knowledge/ingest"


@pytest.mark.parametrize("path,method", [(INGEST, "post"), ("/api/v1/knowledge/index", "post"), ("/api/v1/knowledge/documents", "get")])
def test_requires_auth(client, path, method):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json() == {"detail": "No autenticado"}


def test_invalid_token(client):
    assert client.post(INGEST, json=PAYLOAD, headers={"Authorization": "Bearer invalid"}).status_code == 401


@pytest.mark.parametrize("authorization", ["Basic test-token", "Bearer", "Bearer ", "Bearer    "])
@pytest.mark.parametrize("path,method", [(INGEST, "post"), ("/api/v1/knowledge/index", "post"), ("/api/v1/knowledge/documents", "get")])
def test_missing_bearer_credentials_keep_401(client, authorization, path, method):
    response = getattr(client, method)(path, headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json() == {"detail": "No autenticado"}


def test_openapi_declares_bearer_for_all_knowledge_endpoints(client):
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http", "scheme": "bearer"
    }
    for path, method in [(INGEST, "post"), ("/api/v1/knowledge/index", "post"), ("/api/v1/knowledge/documents", "get")]:
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"HTTPBearer": []}]
        assert not any(p["name"].lower() == "authorization" for p in operation.get("parameters", []))


def test_bearer_token_is_passed_without_scheme_to_existing_verifier(client):
    response = client.post(INGEST, json=PAYLOAD, headers={"Authorization": "bEaReR test-token"})
    # El doble existente solo acepta exactamente "test-token".
    assert response.status_code == 201


def test_source_required_without_global_default(client):
    payload = {k: v for k, v in PAYLOAD.items() if k != "fuente"}
    assert client.post(INGEST, json=payload, headers=AUTH).status_code == 422
    assert client.post(INGEST, json=dict(PAYLOAD, fuente="  "), headers=AUTH).status_code == 400


def test_ingest_list_index_contract_and_duplicate(client):
    response = client.post(INGEST, json=PAYLOAD, headers=AUTH)
    assert response.status_code == 201
    body = response.json()
    assert str(UUID(body["id"])) == body["id"]
    assert set(body) == {"id", "title", "topic", "source_path", "content_hash", "chunk_count", "ingested_at", "status"}
    assert body["status"] == "registered"
    assert body["chunk_count"] == 0
    assert client.post(INGEST, json=PAYLOAD, headers=AUTH).status_code == 409
    assert client.get("/api/v1/knowledge/documents", headers=AUTH).json() == [body]
    indexed = client.post("/api/v1/knowledge/index", headers=AUTH)
    assert indexed.status_code == 200
    result = indexed.json()
    assert set(result) == {"indexed_documents", "total_chunks", "collection", "documents"}
    assert result["indexed_documents"] == 1
    assert result["documents"][0]["status"] == "indexed"
    assert result["documents"][0]["id"] == body["id"]
    assert client.post("/api/v1/knowledge/index", headers=AUTH).json() == result


def test_no_automatic_ingestion_of_sample_files(client):
    assert client.get("/api/v1/knowledge/documents", headers=AUTH).json() == []
    result = client.post("/api/v1/knowledge/index", headers=AUTH).json()
    assert result["indexed_documents"] == 0
    assert result["total_chunks"] == 0


@pytest.mark.parametrize("case", ["valid", "expired", "invalid_signature", "malformed", "missing_sub", "invalid_uuid", "double_bearer"])
def test_real_jwt_verifier_matches_context_and_receives_pure_token(case):
    secret = "isolated-knowledge-test-secret-at-least-32-bytes"
    claims = {"sub": "d5d2d7b5-471e-4e62-8f31-a627a12da725",
              "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    if case == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=5)
    if case == "missing_sub":
        del claims["sub"]
    if case == "invalid_uuid":
        claims["sub"] = "not-a-uuid"
    token = jwt.encode(claims, secret if case != "invalid_signature" else secret + "other", algorithm="HS256")
    if case == "malformed":
        token = "not-a-jwt"
    if case == "double_bearer":
        token = "Bearer " + token
    verifier = Mock(wraps=VerificadorTokenJwt(secret, "HS256"))
    ingest = Mock(wraps=IncorporarConocimiento(RepositorioConocimientoEnMemoria()))
    list_contexts = Mock()
    list_contexts.ejecutar.return_value = []
    container = SimpleNamespace(puerto_verificador_token=verifier,
                                puerto_incorporar_conocimiento=ingest,
                                puerto_listar_contextos_agricolas=list_contexts)
    app = FastAPI()
    app.include_router(create_knowledge_router(container))
    app.include_router(create_context_router(container))
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}
        knowledge = client.post(INGEST, json=PAYLOAD, headers=headers)
        context = client.get("/api/v1/contexts", headers=headers)
    assert verifier.verificar.call_count == 2
    assert all(call.args == (token,) for call in verifier.verificar.call_args_list)
    if case == "valid":
        assert knowledge.status_code == 201
        assert context.status_code == 200
        ingest.ejecutar.assert_called_once()
        list_contexts.ejecutar.assert_called_once_with(claims["sub"])
    else:
        assert knowledge.status_code == context.status_code == 401
        assert knowledge.json() == context.json() == {"detail": "No autenticado"}
        ingest.ejecutar.assert_not_called()
        list_contexts.ejecutar.assert_not_called()
