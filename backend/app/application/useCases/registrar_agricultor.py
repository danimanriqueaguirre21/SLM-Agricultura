from app.domain.entities.agricultor import Agricultor
from app.domain.exceptions import (
    ErrorContrasenaInvalida,
    ErrorCorreoDuplicado,
    ErrorCorreoInvalido,
    ErrorDatosAgricultorInvalidos,
)
from app.domain.ports.input.registrar_agricultor_port import (
    ComandoRegistrarAgricultor,
    PuertoRegistrarAgricultor,
    ResultadoRegistrarAgricultor,
)
from app.domain.ports.output.hasher_contrasena_port import PuertoHasherContrasena
from app.domain.ports.output.repositorio_agricultor_port import PuertoRepositorioAgricultor
from app.domain.valueObjects.email import Email
from app.domain.valueObjects.hash_contrasena import HashContrasena

LONGITUD_MINIMA_CONTRASENA = 8


class RegistrarAgricultor(PuertoRegistrarAgricultor):
    def __init__(
        self,
        repositorio_agricultor: PuertoRepositorioAgricultor,
        hasher_contrasena: PuertoHasherContrasena,
    ) -> None:
        self._repositorio_agricultor = repositorio_agricultor
        self._hasher_contrasena = hasher_contrasena

    def ejecutar(self, comando: ComandoRegistrarAgricultor) -> ResultadoRegistrarAgricultor:
        nombres = (comando.nombres or "").strip()
        apellidos = (comando.apellidos or "").strip()
        if not nombres:
            raise ErrorDatosAgricultorInvalidos("Los nombres son obligatorios")
        if not apellidos:
            raise ErrorDatosAgricultorInvalidos("Los apellidos son obligatorios")

        contrasena = comando.contrasena or ""
        if not contrasena.strip():
            raise ErrorContrasenaInvalida("La contraseña es obligatoria")
        if len(contrasena) < LONGITUD_MINIMA_CONTRASENA:
            raise ErrorContrasenaInvalida("La contraseña debe tener al menos 8 caracteres")

        email = Email(comando.email)
        if len(email.value) > 150:
            raise ErrorCorreoInvalido("El correo no puede superar 150 caracteres")
        if self._repositorio_agricultor.existe_por_correo(email):
            raise ErrorCorreoDuplicado("El correo electrónico ya está registrado")

        hash_contrasena = HashContrasena(self._hasher_contrasena.hashear_contrasena(contrasena))
        agricultor = Agricultor.registrar(
            nombres=nombres,
            apellidos=apellidos,
            email=email,
            hash_contrasena=hash_contrasena,
        )
        self._repositorio_agricultor.guardar(agricultor)
        return ResultadoRegistrarAgricultor(
            id=agricultor.id,
            nombres=agricultor.nombres,
            apellidos=agricultor.apellidos,
            email=agricultor.email.value,
        )
