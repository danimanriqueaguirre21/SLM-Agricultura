from datetime import datetime, timezone
from uuid import uuid4

from app.domain.exceptions import ErrorDocumentoConocimientoInvalido
from app.domain.valueObjects.hash_contenido import HashContenido


class DocumentoConocimiento:
    LONGITUD_MAXIMA_TITULO = 200
    LONGITUD_MAXIMA_TEMA = 50
    LONGITUD_MAXIMA_RUTA = 255
    LONGITUD_MAXIMA_CONTENIDO = 20000

    def __init__(
        self,
        documento_id: str,
        titulo: str,
        ruta_origen: str,
        tema: str,
        hash_contenido: HashContenido,
        cantidad_fragmentos: int,
        incorporado_en: datetime,
        fuente: str = "",
    ) -> None:
        self.id = documento_id
        self.titulo = titulo
        self.ruta_origen = ruta_origen
        self.tema = tema
        self.hash_contenido = hash_contenido
        self.cantidad_fragmentos = cantidad_fragmentos
        self.incorporado_en = incorporado_en
        self.fuente = fuente

    @classmethod
    def crear(
        cls,
        titulo: str,
        tema: str,
        hash_contenido: HashContenido,
    ) -> "DocumentoConocimiento":
        titulo_limpio = (titulo or "").strip()
        tema_limpio = (tema or "").strip()
        if not titulo_limpio:
            raise ErrorDocumentoConocimientoInvalido("El título es obligatorio")
        if len(titulo_limpio) > cls.LONGITUD_MAXIMA_TITULO:
            raise ErrorDocumentoConocimientoInvalido("El título supera la longitud permitida")
        if not tema_limpio:
            raise ErrorDocumentoConocimientoInvalido("El tema es obligatorio")
        if len(tema_limpio) > cls.LONGITUD_MAXIMA_TEMA:
            raise ErrorDocumentoConocimientoInvalido("El tema supera la longitud permitida")

        documento_id = str(uuid4())
        ruta_origen = f"knowledge/{documento_id}.md"
        ahora = datetime.now(timezone.utc).replace(tzinfo=None)
        return cls(
            documento_id=documento_id,
            titulo=titulo_limpio,
            ruta_origen=ruta_origen,
            tema=tema_limpio,
            hash_contenido=hash_contenido,
            cantidad_fragmentos=0,
            incorporado_en=ahora,
        )
