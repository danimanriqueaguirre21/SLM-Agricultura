from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.domain.entities.agricultor import Agricultor
from app.domain.exceptions import ErrorCorreoDuplicado
from app.domain.ports.output.repositorio_agricultor_port import (
    DatosAutenticacionAgricultor,
    PuertoRepositorioAgricultor,
)
from app.domain.valueObjects.email import Email
from app.domain.valueObjects.hash_contrasena import HashContrasena


class RepositorioAgricultorPostgresql(PuertoRepositorioAgricultor):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def existe_por_correo(self, email: Email) -> bool:
        with self._session_factory() as session:
            return bool(session.scalar(
                text("SELECT EXISTS (SELECT 1 FROM usuario WHERE LOWER(email) = :email)"),
                {"email": email.value},
            ))

    def buscar_por_correo(self, email: Email) -> DatosAutenticacionAgricultor | None:
        with self._session_factory() as session:
            registro = session.execute(
                text("SELECT * FROM sp_obtener_usuario_login(p_email => :email)"),
                {"email": email.value},
            ).mappings().one_or_none()
        if registro is None:
            return None
        return DatosAutenticacionAgricultor(
            id_usuario=str(registro["id_usuario"]),
            id_agricultor=(
                str(registro["id_agricultor"])
                if registro["id_agricultor"] is not None else None
            ),
            rol=registro["rol"],
            nombre=registro["nombre"],
            email=Email(registro["email"]),
            hash_contrasena=HashContrasena(registro["password_hash"]),
            estado=registro["estado"],
        )

    def guardar(self, agricultor: Agricultor) -> None:
        with self._session_factory() as session:
            try:
                with session.begin():
                    registro = session.execute(
                        text(
                            "SELECT * FROM sp_registrar_agricultor("
                            "p_nombre => :nombre, p_email => :email, "
                            "p_password_hash => :password_hash)"
                        ),
                        {
                            "nombre": agricultor.nombre_completo,
                            "email": agricultor.email.value,
                            "password_hash": agricultor.hash_contrasena.value,
                        },
                    ).mappings().one()
                    id_agricultor = str(registro["id_agricultor"])
            except DBAPIError as error:
                if _es_correo_duplicado(error):
                    raise ErrorCorreoDuplicado(
                        "El correo electrónico ya está registrado"
                    ) from error
                raise
        # Asignar el ID solo cuando se hayan confirmado ambos registros.
        agricultor.id = id_agricultor

    def actualizar_ultimo_acceso(self, id_usuario: str) -> None:
        with self._session_factory() as session:
            with session.begin():
                session.execute(
                    text(
                        "CALL sp_actualizar_ultimo_acceso("
                        "p_id_usuario => CAST(:id_usuario AS UUID))"
                    ),
                    {"id_usuario": id_usuario},
                )


def _es_correo_duplicado(error: DBAPIError) -> bool:
    original = error.orig
    diagnostico = getattr(original, "diag", None)
    codigo = getattr(original, "sqlstate", None)
    if codigo == "23505":
        return (
            getattr(diagnostico, "constraint_name", None) == "usuario_email_key"
            and getattr(diagnostico, "table_name", None) == "usuario"
        )
    # La rutina existente usa RAISE EXCEPTION sin SQLSTATE propio.
    return (
        codigo == "P0001"
        and getattr(diagnostico, "message_primary", None)
        == "Ya existe un usuario registrado con ese correo"
    )
