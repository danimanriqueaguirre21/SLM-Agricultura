"""Rutinas y transacciones con dobles: ninguna conexión real."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.domain.entities.documento_conocimiento import DocumentoConocimiento
from app.domain.exceptions import ErrorDocumentoConocimientoDuplicado, ErrorDocumentoConocimientoInvalido
from app.domain.ports.output.repositorio_documento_conocimiento_port import FragmentoCatalogo
from app.domain.valueObjects.hash_contenido import HashContenido
from app.infrastructure.adapters.output.mysql.repositorio_documento_conocimiento_postgresql import RepositorioDocumentoConocimientoPostgresql


DOC = str(uuid4())
FRAG = str(uuid4())
HASH = HashContenido.desde_contenido("Texto aprobado")
FRAGMENT = FragmentoCatalogo(f"{HASH.value}:chunk:0000", "Texto aprobado", 0)


def result(*, scalar=None, first=None, rows=()):
    r = MagicMock()
    r.scalar_one.return_value = scalar
    r.first.return_value = first
    r.mappings.return_value.all.return_value = list(rows)
    r.mappings.return_value.first.return_value = first
    return r


@pytest.fixture
def setup(tmp_path):
    session = MagicMock()
    session.__enter__.return_value = session
    factory = MagicMock(return_value=session)
    repo = RepositorioDocumentoConocimientoPostgresql(factory, str(tmp_path))
    return repo, session, factory, tmp_path


def test_register_uses_exact_routine_uuid_and_preserves_bytes(setup):
    repo, session, _, path = setup
    content = "Texto\r\naprobado"
    doc = DocumentoConocimiento.crear("Título", "papa", HashContenido.desde_contenido(content))
    doc.fuente = "Material de prueba local"
    now = datetime.now(timezone.utc)
    session.execute.side_effect = [result(scalar=True), result(), result(scalar=UUID(DOC)), result(scalar=now)]
    repo.guardar(doc, content)
    assert doc.id == DOC
    assert doc.incorporado_en == now
    assert (path / Path(doc.ruta_origen).name).read_bytes() == content.encode()
    assert repo.leer_contenido(doc) == content
    args = session.execute.call_args_list[2].args
    assert str(args[0]) == "SELECT sp_registrar_documento(:titulo, :tipo, :fuente, :autor, :fecha, :url, :ruta)"
    assert args[1]["fuente"] == doc.fuente
    assert args[1]["autor"] is args[1]["fecha"] is args[1]["url"] is None
    session.begin.assert_called_once()


def test_duplicate_checked_under_lock_before_files(setup):
    repo, session, _, path = setup
    doc = DocumentoConocimiento.crear("Título", "papa", HASH)
    doc.fuente = "Fuente explícita"
    session.execute.side_effect = [result(scalar=True), result(first=(DOC,))]
    with pytest.raises(ErrorDocumentoConocimientoDuplicado):
        repo.guardar(doc, "Texto aprobado")
    assert list(path.iterdir()) == []


def test_prepare_persists_null_vector_and_reuses_uuid(setup):
    repo, session, _, _ = setup
    session.execute.side_effect = [result(), result(), result(scalar=UUID(FRAG))]
    assert repo.preparar_fragmentos(DOC, [FRAGMENT]) == [FRAG]
    sql, params = session.execute.call_args.args
    assert str(sql) == "SELECT sp_registrar_fragmento(CAST(:id AS uuid), :contenido, NULL, NULL, NULL, :orden)"
    assert params == {"id": DOC, "contenido": FRAGMENT.contenido, "orden": 0}
    session.execute.reset_mock()
    session.execute.side_effect = [result(rows=[row()]), result()]
    assert repo.preparar_fragmentos(DOC, [FRAGMENT]) == [FRAG]
    assert not any("sp_registrar_fragmento" in str(c.args[0]) for c in session.execute.call_args_list)


def row(**overrides):
    return dict(id_fragmento=UUID(FRAG), contenido=FRAGMENT.contenido, vector_id=None, orden_fragmento=0, **overrides)


def test_confirm_calls_procedure_with_exact_vector_id(setup):
    repo, session, _, _ = setup
    session.execute.side_effect = [result(rows=[row()]), result()]
    repo.confirmar_fragmentos(DOC, [FRAGMENT])
    sql, params = session.execute.call_args.args
    assert str(sql) == "CALL sp_actualizar_vector_fragmento(CAST(:id AS uuid), :vector)"
    assert params == {"id": FRAG, "vector": FRAGMENT.vector_id}
    session.begin.assert_called_once()


def test_confirmation_failure_exits_transaction_with_error(setup):
    repo, session, _, _ = setup
    session.execute.side_effect = [result(rows=[row()]), RuntimeError("SQL falló")]
    with pytest.raises(RuntimeError, match="SQL falló"):
        repo.confirmar_fragmentos(DOC, [FRAGMENT])
    assert session.begin.return_value.__exit__.call_args.args[0] is RuntimeError


def test_fragment_registration_failure_rolls_back_batch(setup):
    repo, session, _, _ = setup
    second = FragmentoCatalogo(f"{HASH.value}:chunk:0001", "Segundo", 1)
    session.execute.side_effect = [result(), result(), result(scalar=FRAG), result(), RuntimeError("SQL falló")]
    with pytest.raises(RuntimeError):
        repo.preparar_fragmentos(DOC, [FRAGMENT, second])
    assert session.begin.return_value.__exit__.call_args.args[0] is RuntimeError


def test_partial_catalog_reuses_first_and_creates_only_missing_fragment(setup):
    repo, session, _, _ = setup
    second = FragmentoCatalogo(f"{HASH.value}:chunk:0001", "Segundo", 1)
    second_id = str(uuid4())
    session.execute.side_effect = [result(rows=[row()]), result(), result(), result(scalar=second_id)]
    assert repo.preparar_fragmentos(DOC, [FRAGMENT, second]) == [FRAG, second_id]
    registrations = [c for c in session.execute.call_args_list if "sp_registrar_fragmento" in str(c.args[0])]
    assert len(registrations) == 1
    assert registrations[0].args[1]["orden"] == 1


@pytest.mark.parametrize("rows", [[row(), row()], [dict(row(), contenido="Distinto")], [dict(row(), orden_fragmento=5)]])
def test_inconsistent_fragmentation_rejected(setup, rows):
    repo, session, _, _ = setup
    session.execute.return_value = result(rows=rows)
    with pytest.raises(ErrorDocumentoConocimientoInvalido):
        repo.preparar_fragmentos(DOC, [FRAGMENT])
    assert session.execute.call_count == 1


def test_cross_document_vector_collision_rejected(setup):
    repo, session, _, _ = setup
    session.execute.side_effect = [result(), result(first=(FRAG,))]
    with pytest.raises(ErrorDocumentoConocimientoInvalido, match="ambiguo"):
        repo.preparar_fragmentos(DOC, [FRAGMENT])


def test_resolver_uses_existing_routine_preserves_strings_and_rejects_duplicates(setup):
    repo, session, _, _ = setup
    resolved = {"id_fragmento": UUID(FRAG), "id_documento": UUID(DOC), "vector_id": FRAGMENT.vector_id}
    session.execute.return_value = result(rows=[resolved])
    assert repo.resolver_vectores([FRAGMENT.vector_id]) == [dict(resolved, id_fragmento=FRAG, id_documento=DOC)]
    assert str(session.execute.call_args.args[0]) == "SELECT * FROM sp_obtener_fragmentos_por_vector_ids(CAST(:ids AS text[]))"
    session.execute.return_value = result(rows=[resolved, resolved])
    with pytest.raises(ErrorDocumentoConocimientoInvalido, match="ambiguo"):
        repo.resolver_vectores([FRAGMENT.vector_id])


def test_lock_uses_dedicated_autocommit_connection_and_unlocks_on_failure(setup):
    repo, _, factory, _ = setup
    conn = MagicMock()
    factory.kw["bind"].connect.return_value.execution_options.return_value.__enter__.return_value = conn
    conn.execute.return_value = result(scalar=True)
    with pytest.raises(RuntimeError):
        with repo.bloquear_indexacion():
            raise RuntimeError("Embedding falló")
    assert "pg_try_advisory_lock" in str(conn.execute.call_args_list[0].args[0])
    assert "pg_advisory_unlock" in str(conn.execute.call_args_list[1].args[0])
    factory.kw["bind"].connect.return_value.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")


def test_no_integer_ids_or_legacy_table():
    source = Path(__file__).parents[1] / "app/infrastructure/adapters/output/mysql/repositorio_documento_conocimiento_postgresql.py"
    text = source.read_text(encoding="utf-8")
    assert "int(" not in text
    assert "id_a_entero" not in text
    assert "documentos_conocimiento" not in text


def test_list_uses_active_routine_and_relational_confirmed_count(setup):
    repo, session, _, path = setup
    ruta = f"knowledge/{HASH.value}.md"
    (path / f"{HASH.value}.meta.json").write_text('{"topic":"papa"}', encoding="utf-8")
    data = {"id_documento": UUID(DOC), "titulo": "Título", "fuente": "Fuente explícita",
            "ruta_archivo": ruta, "fecha_ingreso": datetime.now(timezone.utc)}
    session.execute.side_effect = [result(rows=[data]), result(scalar=2)]
    docs = repo.listar_todos()
    assert str(session.execute.call_args_list[0].args[0]) == "SELECT * FROM sp_listar_documentos_activos()"
    assert docs[0].id == DOC
    assert docs[0].fuente == "Fuente explícita"
    assert docs[0].cantidad_fragmentos == 2
    assert docs[0].hash_contenido == HASH
    assert "vector_id IS NOT NULL" in str(session.execute.call_args_list[1].args[0])


def test_missing_sidecar_is_not_silently_accepted(setup):
    repo, session, _, _ = setup
    session.execute.return_value = result(rows=[{"ruta_archivo": f"knowledge/{HASH.value}.md"}])
    with pytest.raises(ErrorDocumentoConocimientoInvalido, match="Metadatos"):
        repo.listar_todos()


def test_busy_lock_does_not_enter_indexing(setup):
    repo, _, factory, _ = setup
    conn = MagicMock()
    factory.kw["bind"].connect.return_value.execution_options.return_value.__enter__.return_value = conn
    conn.execute.return_value = result(scalar=False)
    with pytest.raises(ErrorDocumentoConocimientoInvalido, match="ocupado"):
        with repo.bloquear_indexacion():
            pytest.fail("No debe entrar")
    assert conn.execute.call_count == 1


def test_sql_error_is_not_mapped_to_duplicate_and_files_remain_for_retry(setup):
    repo, session, _, path = setup
    doc = DocumentoConocimiento.crear("Título", "papa", HASH)
    doc.fuente = "Fuente explícita"
    session.execute.side_effect = [result(scalar=True), result(), RuntimeError("Commit o SQL incierto")]
    with pytest.raises(RuntimeError, match="incierto"):
        repo.guardar(doc, "Texto aprobado")
    assert (path / f"{HASH.value}.md").read_text() == "Texto aprobado"
    assert session.begin.return_value.__exit__.call_args.args[0] is RuntimeError
