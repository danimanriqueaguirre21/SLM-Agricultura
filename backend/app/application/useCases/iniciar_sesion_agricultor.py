from app.domain.exceptions import ErrorCorreoInvalido, ErrorCredencialesInvalidas
from app.domain.ports.input.iniciar_sesion_agricultor_port import (
    AgricultorAutenticado,
    ComandoIniciarSesionAgricultor,
    PuertoIniciarSesionAgricultor,
    ResultadoIniciarSesionAgricultor,
)
from app.domain.ports.output.hasher_contrasena_port import PuertoHasherContrasena
from app.domain.ports.output.repositorio_agricultor_port import PuertoRepositorioAgricultor
from app.domain.ports.output.token_issuer_port import PuertoEmisorToken
from app.domain.valueObjects.email import Email

CREDENCIALES_INVALIDAS = "Credenciales inválidas"


class IniciarSesionAgricultor(PuertoIniciarSesionAgricultor):
    def __init__(
        self,
        repositorio_agricultor: PuertoRepositorioAgricultor,
        hasher_contrasena: PuertoHasherContrasena,
        emisor_token: PuertoEmisorToken,
    ) -> None:
        self._repositorio_agricultor = repositorio_agricultor
        self._hasher_contrasena = hasher_contrasena
        self._emisor_token = emisor_token

    def ejecutar(
        self, comando: ComandoIniciarSesionAgricultor
    ) -> ResultadoIniciarSesionAgricultor:
        contrasena = comando.contrasena or ""
        if not contrasena.strip():
            raise ErrorCredencialesInvalidas(CREDENCIALES_INVALIDAS)

        try:
            email = Email(comando.email)
        except ErrorCorreoInvalido:
            raise

        agricultor = self._repositorio_agricultor.buscar_por_correo(email)
        if (
            agricultor is None
            or agricultor.estado != "ACTIVO"
            or agricultor.rol != "AGRICULTOR"
            or not agricultor.id_agricultor
        ):
            raise ErrorCredencialesInvalidas(CREDENCIALES_INVALIDAS)

        if not self._hasher_contrasena.verificar_contrasena(
            contrasena, agricultor.hash_contrasena.value
        ):
            raise ErrorCredencialesInvalidas(CREDENCIALES_INVALIDAS)

        self._repositorio_agricultor.actualizar_ultimo_acceso(agricultor.id_usuario)
        partes_nombre = agricultor.nombre.strip().split(" ", 1)
        nombres = partes_nombre[0]
        apellidos = partes_nombre[1] if len(partes_nombre) > 1 else ""

        access_token = self._emisor_token.emitir_token(
            sujeto=agricultor.id_agricultor,
            claims={"email": agricultor.email.value},
        )
        return ResultadoIniciarSesionAgricultor(
            access_token=access_token,
            token_type="bearer",
            agricultor=AgricultorAutenticado(
                id=agricultor.id_agricultor,
                nombres=nombres,
                apellidos=apellidos,
                email=agricultor.email.value,
            ),
        )
