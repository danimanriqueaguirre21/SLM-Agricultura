from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.domain.entities.contexto_agricola import ContextoAgricola
from app.domain.exceptions import ErrorContextoNoEncontrado, ErrorDatosContextoInvalidos
from app.domain.ports.output.repositorio_contexto_agricola_port import (
    PuertoRepositorioContextoAgricola,
)
from app.domain.valueObjects.cultivo import Cultivo
from app.domain.valueObjects.region import Region


def _uuid(valor: str, *, contexto: bool = False) -> str:
    try:
        return str(UUID(str(valor)))
    except (ValueError, TypeError, AttributeError) as error:
        if contexto:
            raise ErrorContextoNoEncontrado("Contexto agrícola no encontrado") from error
        raise ErrorDatosContextoInvalidos("El agricultor debe tener un UUID válido") from error


class RepositorioContextoAgricolaPostgresql(PuertoRepositorioContextoAgricola):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def guardar(self, contexto: ContextoAgricola) -> None:
        agricultor_id = _uuid(contexto.agricultor_id)
        try:
            with self._session_factory() as session:
                with session.begin():
                    parcela_id = session.scalar(
                        text(
                            "SELECT sp_registrar_parcela("
                            "p_id_agricultor => CAST(:agricultor_id AS UUID), "
                            "p_nombre => CAST(:nombre AS VARCHAR), "
                            "p_ubicacion => CAST(:ubicacion AS VARCHAR))"
                        ),
                        {"agricultor_id": agricultor_id,
                         "nombre": contexto.nombre_predio,
                         "ubicacion": contexto.region.value},
                    )
                    cultivo_id = session.scalar(
                        text(
                            "SELECT sp_registrar_cultivo("
                            "p_id_parcela => CAST(:parcela_id AS UUID), "
                            "p_nombre_comun => CAST(:cultivo AS VARCHAR), "
                            "p_observaciones => CAST(:notas AS TEXT))"
                        ),
                        {"parcela_id": str(parcela_id), "cultivo": contexto.cultivo.value,
                         "notas": contexto.observaciones},
                    )
                    guardado = self._buscar(session, str(cultivo_id), agricultor_id)
                    if guardado is None:
                        raise ErrorContextoNoEncontrado("No se pudo recuperar el contexto creado")
        except DBAPIError as error:
            if _error_rutina(error, "P0001", "Agricultor no encontrado"):
                raise ErrorDatosContextoInvalidos("Agricultor no encontrado") from error
            raise
        # Publicar los datos persistidos solo después de confirmar ambas inserciones.
        contexto.id = guardado.id
        contexto.agricultor_id = guardado.agricultor_id
        contexto.nombre_predio = guardado.nombre_predio
        contexto.cultivo = guardado.cultivo
        contexto.region = guardado.region
        contexto.observaciones = guardado.observaciones
        contexto.creado_en = guardado.creado_en
        contexto.esta_seleccionado = guardado.esta_seleccionado

    def listar_por_agricultor(self, agricultor_id: str) -> list[ContextoAgricola]:
        agricultor_id = _uuid(agricultor_id)
        with self._session_factory() as session:
            registros = session.execute(
                text("SELECT * FROM sp_listar_cultivos_agricultor("
                     "p_id_agricultor => CAST(:agricultor_id AS UUID))"),
                {"agricultor_id": agricultor_id},
            ).mappings().all()
            return [self._a_entidad(registro, agricultor_id) for registro in registros]

    def buscar_por_id_para_agricultor(
        self, contexto_id: str, agricultor_id: str
    ) -> ContextoAgricola | None:
        contexto_id = _uuid(contexto_id, contexto=True)
        agricultor_id = _uuid(agricultor_id)
        with self._session_factory() as session:
            return self._buscar(session, contexto_id, agricultor_id)

    def seleccionar_para_agricultor(
        self, contexto_id: str, agricultor_id: str
    ) -> ContextoAgricola | None:
        contexto_id = _uuid(contexto_id, contexto=True)
        agricultor_id = _uuid(agricultor_id)
        try:
            with self._session_factory() as session:
                with session.begin():
                    session.scalar(
                        text("SELECT sp_seleccionar_cultivo("
                             "p_id_agricultor => CAST(:agricultor_id AS UUID), "
                             "p_id_cultivo => CAST(:contexto_id AS UUID))"),
                        {"agricultor_id": agricultor_id, "contexto_id": contexto_id},
                    )
                    seleccionado = self._buscar(session, contexto_id, agricultor_id)
                    if seleccionado is None:
                        raise ErrorContextoNoEncontrado("Contexto agrícola no encontrado")
                return seleccionado
        except DBAPIError as error:
            if _error_rutina(error, "P0002", "Cultivo no encontrado para el agricultor"):
                return None
            raise

    def _buscar(self, session, contexto_id: str, agricultor_id: str) -> ContextoAgricola | None:
        registro = session.execute(
            text("SELECT * FROM sp_obtener_contexto_cultivo("
                 "p_id_agricultor => CAST(:agricultor_id AS UUID), "
                 "p_id_cultivo => CAST(:contexto_id AS UUID))"),
            {"agricultor_id": agricultor_id, "contexto_id": contexto_id},
        ).mappings().one_or_none()
        return self._a_entidad(registro, agricultor_id) if registro is not None else None

    @staticmethod
    def _a_entidad(registro, agricultor_id: str) -> ContextoAgricola:
        return ContextoAgricola(
            contexto_id=str(registro["id_cultivo"]),
            agricultor_id=agricultor_id,
            nombre_predio=registro["parcela"],
            cultivo=Cultivo(registro["nombre_comun"]),
            region=Region(registro["ubicacion"]),
            observaciones=registro["observaciones"],
            esta_seleccionado=registro["esta_seleccionado"],
            creado_en=registro["fecha_creacion"],
        )


def _error_rutina(error: DBAPIError, codigo: str, mensaje: str) -> bool:
    return (
        getattr(error.orig, "sqlstate", None) == codigo
        and getattr(getattr(error.orig, "diag", None), "message_primary", None) == mensaje
    )
