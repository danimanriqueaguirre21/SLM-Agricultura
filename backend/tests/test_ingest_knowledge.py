from pathlib import Path

import pytest

from app.application.useCases.incorporar_conocimiento import IncorporarConocimiento
from app.domain.entities.documento_conocimiento import DocumentoConocimiento
from app.domain.exceptions import (
    ErrorDocumentoConocimientoDuplicado,
    ErrorDocumentoConocimientoInvalido,
)
from app.domain.ports.input.incorporar_conocimiento_port import ComandoIncorporarConocimiento
from app.domain.ports.output.repositorio_documento_conocimiento_port import (
    PuertoRepositorioDocumentoConocimiento,
)
from app.domain.valueObjects.hash_contenido import HashContenido

CONTENT = """# Riego de papa (material de prueba)

Texto de prueba para HU-05. No es una guía oficial.
"""


class RepositorioConocimientoEnMemoria(PuertoRepositorioDocumentoConocimiento):
    def __init__(self) -> None:
        self.documentos: list[DocumentoConocimiento] = []
        self.contenidos: dict[str, str] = {}

    def existe_por_hash(self, hash_contenido: HashContenido) -> bool:
        return any(documento.hash_contenido == hash_contenido for documento in self.documentos)

    def guardar(self, documento: DocumentoConocimiento, contenido: str) -> None:
        self.documentos.append(documento)
        self.contenidos[documento.id] = contenido

    def listar_todos(self) -> list[DocumentoConocimiento]:
        return list(self.documentos)

    def buscar_por_id(self, documento_id: str) -> DocumentoConocimiento | None:
        for documento in self.documentos:
            if documento.id == documento_id:
                return documento
        return None

    def leer_contenido(self, documento: DocumentoConocimiento) -> str:
        return self.contenidos[documento.id]

    def actualizar_cantidad_fragmentos(self, documento_id: str, cantidad_fragmentos: int) -> None:
        for documento in self.documentos:
            if documento.id == documento_id:
                documento.cantidad_fragmentos = cantidad_fragmentos
                return


def _caso_de_uso() -> tuple[IncorporarConocimiento, RepositorioConocimientoEnMemoria]:
    repositorio = RepositorioConocimientoEnMemoria()
    return IncorporarConocimiento(repositorio), repositorio


def test_ingest_knowledge_success() -> None:
    use_case, repository = _caso_de_uso()
    result = use_case.ejecutar(
        ComandoIncorporarConocimiento(fuente="Material de prueba local", titulo="Riego de papa", tema="papa", contenido=CONTENT)
    )
    assert result.estado == "registered"
    assert result.titulo == "Riego de papa"
    assert result.tema == "papa"
    assert result.cantidad_fragmentos == 0
    assert result.ruta_origen.endswith(".md")
    assert len(result.hash_contenido) == 64
    assert len(repository.documentos) == 1


def test_ingest_knowledge_empty_content() -> None:
    use_case, _repository = _caso_de_uso()
    with pytest.raises(ErrorDocumentoConocimientoInvalido, match="contenido"):
        use_case.ejecutar(
            ComandoIncorporarConocimiento(fuente="Material de prueba local", titulo="Riego", tema="papa", contenido="   ")
        )


def test_ingest_knowledge_invalid_content_too_long() -> None:
    use_case, _repository = _caso_de_uso()
    with pytest.raises(ErrorDocumentoConocimientoInvalido, match="longitud"):
        use_case.ejecutar(
            ComandoIncorporarConocimiento(fuente="Material de prueba local",
                titulo="Riego",
                tema="papa",
                contenido="a" * (DocumentoConocimiento.LONGITUD_MAXIMA_CONTENIDO + 1),
            )
        )


def test_content_hash_is_deterministic() -> None:
    first = HashContenido.desde_contenido(CONTENT)
    second = HashContenido.desde_contenido(CONTENT)
    other = HashContenido.desde_contenido(CONTENT + " distinto")
    assert first == second
    assert first.value == second.value
    assert first != other
    assert len(first.value) == 64


def test_ingest_knowledge_duplicate_content() -> None:
    use_case, repository = _caso_de_uso()
    command = ComandoIncorporarConocimiento(fuente="Material de prueba local",
        titulo="Riego de papa", tema="papa", contenido=CONTENT
    )
    use_case.ejecutar(command)
    with pytest.raises(ErrorDocumentoConocimientoDuplicado, match="ya está registrado"):
        use_case.ejecutar(
            ComandoIncorporarConocimiento(fuente="Material de prueba local", titulo="Copia de riego", tema="papa", contenido=CONTENT)
        )
    assert len(repository.documentos) == 1


def test_ingest_knowledge_persists_document_and_content() -> None:
    use_case, repository = _caso_de_uso()
    result = use_case.ejecutar(
        ComandoIncorporarConocimiento(fuente="Material de prueba local", titulo="Riego de papa", tema="papa", contenido=CONTENT)
    )
    stored = repository.buscar_por_id(result.id)
    assert stored is not None
    assert stored.titulo == "Riego de papa"
    assert repository.contenidos[result.id] == CONTENT.strip()
    assert stored.cantidad_fragmentos == 0


def test_ingest_knowledge_uses_ports_not_adapters() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "application"
        / "useCases"
        / "incorporar_conocimiento.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "puertorepositoriodocumentoconocimiento" in lowered
    assert "repositoriodocumentoconocimientomysql" not in lowered
    assert "externalembeddingadapter" not in lowered


def test_ingest_knowledge_use_case_does_not_import_frameworks_or_sdks() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "application"
        / "useCases"
        / "incorporar_conocimiento.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "chromadb",
        "openai",
        "anthropic",
        "langchain",
        "httpx",
        "pydantic",
        "import jwt",
        "from jwt",
        "pymysql",
    )
    for item in forbidden:
        assert item not in lowered


def test_ingest_knowledge_does_not_generate_embeddings() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "application"
        / "useCases"
        / "incorporar_conocimiento.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "embeddingport" not in lowered
    assert "embed_text" not in lowered
    assert "embed_texts" not in lowered
    assert "chromadb" not in lowered
    assert "vectorstore" not in lowered
