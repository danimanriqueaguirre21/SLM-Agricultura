from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.entities.documento_conocimiento import DocumentoConocimiento


@dataclass(frozen=True)
class ComandoIncorporarConocimiento:
    titulo: str
    tema: str
    contenido: str
    fuente: str = ""


@dataclass(frozen=True)
class ResultadoDocumentoConocimiento:
    id: str
    titulo: str
    tema: str
    ruta_origen: str
    hash_contenido: str
    cantidad_fragmentos: int
    incorporado_en: str
    estado: str


class PuertoIncorporarConocimiento(ABC):
    @abstractmethod
    def ejecutar(self, comando: ComandoIncorporarConocimiento) -> ResultadoDocumentoConocimiento:
        """Incorpora un documento de conocimiento agrícola."""


class PuertoListarDocumentosConocimiento(ABC):
    @abstractmethod
    def ejecutar(self) -> list[ResultadoDocumentoConocimiento]:
        """Lista los documentos de conocimiento registrados."""


def documento_a_resultado(
    documento: DocumentoConocimiento,
    estado: str = "registered",
) -> ResultadoDocumentoConocimiento:
    return ResultadoDocumentoConocimiento(
        id=documento.id,
        titulo=documento.titulo,
        tema=documento.tema,
        ruta_origen=documento.ruta_origen,
        hash_contenido=documento.hash_contenido.value,
        cantidad_fragmentos=documento.cantidad_fragmentos,
        incorporado_en=documento.incorporado_en.isoformat(),
        estado=estado,
    )
