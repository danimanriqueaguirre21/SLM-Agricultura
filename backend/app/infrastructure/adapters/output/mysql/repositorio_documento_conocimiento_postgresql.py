"""Catálogo Etapa 3A. No inicializa tablas ni el índice vectorial."""
import json
import re
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.domain.entities.documento_conocimiento import DocumentoConocimiento
from app.domain.exceptions import (
    ErrorArchivoConocimientoNoEncontrado,
    ErrorDocumentoConocimientoDuplicado,
    ErrorDocumentoConocimientoInvalido,
)
from app.domain.ports.output.repositorio_documento_conocimiento_port import (
    FragmentoCatalogo, PuertoCatalogoDocumental,
)
from app.domain.valueObjects.hash_contenido import HashContenido


# Compartido por incorporación e indexación. No sustituye restricciones UNIQUE.
CATALOGO_LOCK = 730031


class RepositorioDocumentoConocimientoPostgresql(PuertoCatalogoDocumental):
    def __init__(self, session_factory, knowledge_dir: str):
        self._session_factory = session_factory
        self._directorio = Path(knowledge_dir)

    @contextmanager
    def bloquear_indexacion(self):
        # Conexión dedicada: un Session.commit() podría devolver la conexión al pool
        # y dejar un advisory lock de sesión en una conexión diferente.
        engine = self._session_factory.kw["bind"]
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            acquired = conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": CATALOGO_LOCK}).scalar_one()
            if not acquired:
                raise ErrorDocumentoConocimientoInvalido("El catálogo está ocupado; reintente después")
            try:
                yield
            finally:
                try:
                    conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": CATALOGO_LOCK})
                except BaseException:
                    conn.invalidate()
                    raise

    @staticmethod
    def _ruta(hash_contenido):
        return f"knowledge/{hash_contenido.value}.md"

    def existe_por_hash(self, hash_contenido):
        with self._session_factory() as session:
            return session.execute(text("SELECT id_documento FROM documento WHERE ruta_archivo=:ruta"),
                                   {"ruta": self._ruta(hash_contenido)}).first() is not None

    def guardar(self, documento, contenido):
        if not documento.fuente.strip() or len(documento.fuente) > 150:
            raise ErrorDocumentoConocimientoInvalido("La fuente es obligatoria y admite hasta 150 caracteres")
        if HashContenido.desde_contenido(contenido) != documento.hash_contenido:
            raise ErrorDocumentoConocimientoInvalido("Hash del documento inconsistente")
        ruta = self._ruta(documento.hash_contenido)
        with self._session_factory() as session, session.begin():
            acquired = session.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": CATALOGO_LOCK}).scalar_one()
            if not acquired:
                raise ErrorDocumentoConocimientoInvalido("El catálogo está ocupado; reintente después")
            if session.execute(text("SELECT id_documento FROM documento WHERE ruta_archivo=:ruta"), {"ruta": ruta}).first():
                raise ErrorDocumentoConocimientoDuplicado("El documento de conocimiento ya está registrado")
            self._directorio.mkdir(parents=True, exist_ok=True)
            archivo = self._directorio / Path(ruta).name
            # Bytes exactos: no conversión de saltos de línea en Windows.
            if archivo.exists() and archivo.read_bytes() != contenido.encode("utf-8"):
                raise ErrorDocumentoConocimientoInvalido("Archivo existente con contenido contradictorio")
            archivo.write_bytes(contenido.encode("utf-8"))
            archivo.with_suffix(".meta.json").write_text(json.dumps({"topic": documento.tema}, ensure_ascii=False), encoding="utf-8")
            documento.id = str(UUID(str(session.execute(text(
                "SELECT sp_registrar_documento(:titulo, :tipo, :fuente, :autor, :fecha, :url, :ruta)"
            ), {"titulo": documento.titulo, "tipo": "Markdown", "fuente": documento.fuente,
                "autor": None, "fecha": None, "url": None, "ruta": ruta}).scalar_one())))
            documento.incorporado_en = session.execute(text(
                "SELECT fecha_ingreso FROM documento WHERE id_documento=CAST(:id AS uuid)"
            ), {"id": documento.id}).scalar_one()
            documento.ruta_origen = ruta
        # No borrar archivos en errores de commit: el resultado puede ser incierto.
        # Un reintento verifica PostgreSQL primero y recupera archivos huérfanos.

    def listar_todos(self):
        with self._session_factory() as session:
            rows = session.execute(text("SELECT * FROM sp_listar_documentos_activos()")).mappings().all()
            return [self._a_entidad(session, row) for row in rows]

    def buscar_por_id(self, documento_id):
        documento_id = str(UUID(str(documento_id)))
        with self._session_factory() as session:
            row = session.execute(text("SELECT * FROM sp_listar_documentos_activos() WHERE id_documento=CAST(:id AS uuid)"), {"id": documento_id}).mappings().first()
            return self._a_entidad(session, row) if row else None

    def _a_entidad(self, session, row):
        ruta = row["ruta_archivo"] or ""
        if not re.fullmatch(r"knowledge/[0-9a-f]{64}\.md", ruta):
            raise ErrorDocumentoConocimientoInvalido("Documento sin archivo compatible con Etapa 3A")
        archivo = self._directorio / Path(ruta).name
        try:
            meta = json.loads(archivo.with_suffix(".meta.json").read_text(encoding="utf-8"))
            tema = meta["topic"]
            if not isinstance(tema, str) or not tema.strip():
                raise ValueError("Tema vacío")
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ErrorDocumentoConocimientoInvalido("Metadatos locales ausentes o inválidos") from error
        cantidad = session.execute(text("SELECT COUNT(*) FROM fragmento WHERE id_documento=CAST(:id AS uuid) AND vector_id IS NOT NULL"), {"id": str(row["id_documento"])}).scalar_one()
        return DocumentoConocimiento(str(UUID(str(row["id_documento"]))), row["titulo"], ruta, tema,
                                     HashContenido(Path(ruta).stem), cantidad, row["fecha_ingreso"], row["fuente"])

    def leer_contenido(self, documento):
        try:
            return (self._directorio / Path(documento.ruta_origen).name).read_bytes().decode("utf-8")
        except FileNotFoundError as error:
            raise ErrorArchivoConocimientoNoEncontrado("No se encontró el archivo del documento") from error

    def actualizar_cantidad_fragmentos(self, documento_id, cantidad_fragmentos):
        # Derivada de fragmento; no hay contador redundante en documento.
        UUID(str(documento_id))

    @staticmethod
    def _existentes(session, documento_id):
        return session.execute(text("SELECT id_fragmento,contenido,vector_id,orden_fragmento FROM fragmento WHERE id_documento=CAST(:id AS uuid) ORDER BY orden_fragmento"), {"id": documento_id}).mappings().all()

    @staticmethod
    def _validar_existentes(rows, fragmentos):
        por_orden = {f.orden: f for f in fragmentos}
        if len(por_orden) != len(fragmentos) or set(por_orden) != set(range(len(fragmentos))):
            raise ErrorDocumentoConocimientoInvalido("Orden de fragmentos inválido")
        existentes = {}
        for row in rows:
            orden = row["orden_fragmento"]
            esperado = por_orden.get(orden)
            if (orden in existentes or esperado is None or row["contenido"] != esperado.contenido
                    or row["vector_id"] not in (None, esperado.vector_id)):
                raise ErrorDocumentoConocimientoInvalido("Fragmentación incompatible; no se sobrescribirán vectores")
            existentes[orden] = row
        return existentes

    def preparar_fragmentos(self, documento_id: str, fragmentos: list[FragmentoCatalogo]):
        documento_id = str(UUID(str(documento_id)))
        with self._session_factory() as session, session.begin():
            existentes = self._validar_existentes(self._existentes(session, documento_id), fragmentos)
            ids = []
            for f in fragmentos:
                conflicto = session.execute(text("SELECT id_fragmento FROM fragmento WHERE vector_id=:vector AND (id_documento<>CAST(:id AS uuid) OR orden_fragmento IS DISTINCT FROM :orden)"), {"vector": f.vector_id, "id": documento_id, "orden": f.orden}).first()
                if conflicto:
                    raise ErrorDocumentoConocimientoInvalido("ID vectorial ambiguo")
                row = existentes.get(f.orden)
                fragmento_id = row["id_fragmento"] if row else session.execute(text(
                    "SELECT sp_registrar_fragmento(CAST(:id AS uuid), :contenido, NULL, NULL, NULL, :orden)"
                ), {"id": documento_id, "contenido": f.contenido, "orden": f.orden}).scalar_one()
                ids.append(str(UUID(str(fragmento_id))))
            return ids

    def confirmar_fragmentos(self, documento_id, fragmentos):
        documento_id = str(UUID(str(documento_id)))
        with self._session_factory() as session, session.begin():
            rows = self._validar_existentes(self._existentes(session, documento_id), fragmentos)
            if len(rows) != len(fragmentos):
                raise ErrorDocumentoConocimientoInvalido("Faltan fragmentos pendientes")
            for f in fragmentos:
                session.execute(text("CALL sp_actualizar_vector_fragmento(CAST(:id AS uuid), :vector)"),
                                {"id": str(rows[f.orden]["id_fragmento"]), "vector": f.vector_id})

    def resolver_vectores(self, vector_ids):
        with self._session_factory() as session:
            rows = session.execute(text("SELECT * FROM sp_obtener_fragmentos_por_vector_ids(CAST(:ids AS text[]))"), {"ids": vector_ids}).mappings().all()
            resultado = []
            vistos = set()
            for row in rows:
                if row["vector_id"] in vistos:
                    raise ErrorDocumentoConocimientoInvalido("ID vectorial ambiguo")
                vistos.add(row["vector_id"])
                item = dict(row)
                for key in ("id_documento", "id_fragmento"):
                    item[key] = str(UUID(str(item[key])))
                resultado.append(item)
            return resultado
