from app.domain.entities.documento_conocimiento import DocumentoConocimiento
from app.domain.exceptions import (
    ErrorDocumentoConocimientoDuplicado,
    ErrorDocumentoConocimientoInvalido,
)
from app.domain.ports.input.incorporar_conocimiento_port import (
    ComandoIncorporarConocimiento,
    PuertoIncorporarConocimiento,
    ResultadoDocumentoConocimiento,
    documento_a_resultado,
)
from app.domain.ports.output.repositorio_documento_conocimiento_port import (
    PuertoRepositorioDocumentoConocimiento,
)
from app.domain.valueObjects.hash_contenido import HashContenido


class IncorporarConocimiento(PuertoIncorporarConocimiento):
    def __init__(self, repositorio_conocimiento: PuertoRepositorioDocumentoConocimiento) -> None:
        self._repositorio_conocimiento = repositorio_conocimiento

    def ejecutar(self, comando: ComandoIncorporarConocimiento) -> ResultadoDocumentoConocimiento:
        contenido = _contenido_validado(comando.contenido)
        fuente = comando.fuente.strip()
        if not fuente or len(fuente) > 150:
            raise ErrorDocumentoConocimientoInvalido("La fuente es obligatoria y admite hasta 150 caracteres")
        hash_contenido = HashContenido.desde_contenido(contenido)
        if self._repositorio_conocimiento.existe_por_hash(hash_contenido):
            raise ErrorDocumentoConocimientoDuplicado(
                "El documento de conocimiento ya está registrado"
            )

        documento = DocumentoConocimiento.crear(
            titulo=comando.titulo,
            tema=comando.tema,
            hash_contenido=hash_contenido,
        )
        documento.fuente = fuente
        self._repositorio_conocimiento.guardar(documento, contenido)
        return documento_a_resultado(documento, estado="registered")


def _contenido_validado(contenido: str) -> str:
    if contenido is None:
        raise ErrorDocumentoConocimientoInvalido("El contenido es obligatorio")
    limpio = str(contenido).strip()
    if not limpio:
        raise ErrorDocumentoConocimientoInvalido("El contenido es obligatorio")
    if len(limpio) > DocumentoConocimiento.LONGITUD_MAXIMA_CONTENIDO:
        raise ErrorDocumentoConocimientoInvalido("El contenido supera la longitud permitida")
    return limpio
