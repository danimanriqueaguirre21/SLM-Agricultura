from app.application.services.fragmentador_documentos import FragmentadorDocumentos, FragmentoDocumento
from app.domain.entities.documento_conocimiento import DocumentoConocimiento
from app.domain.exceptions import ErrorDocumentoConocimientoInvalido
from app.domain.valueObjects.hash_contenido import HashContenido
from app.domain.ports.input.incorporar_conocimiento_port import documento_a_resultado
from app.domain.ports.input.indexar_conocimiento_port import (
    PuertoIndexarConocimiento,
    ResultadoIndexarConocimiento,
)
from app.domain.ports.output.embedding_port import EmbeddingPort
from app.domain.ports.output.repositorio_documento_conocimiento_port import (
    PuertoCatalogoDocumental, FragmentoCatalogo,
)
from app.domain.ports.output.vector_store_port import VectorRecord, VectorStorePort


class IndexarConocimiento(PuertoIndexarConocimiento):
    def __init__(
        self,
        repositorio_conocimiento: PuertoCatalogoDocumental,
        embedding_port: EmbeddingPort,
        almacen_vectores: VectorStorePort,
        fragmentador: FragmentadorDocumentos,
    ) -> None:
        self._repositorio_conocimiento = repositorio_conocimiento
        self._embedding_port = embedding_port
        self._almacen_vectores = almacen_vectores
        self._fragmentador = fragmentador

    def ejecutar(self) -> ResultadoIndexarConocimiento:
        with self._repositorio_conocimiento.bloquear_indexacion():
            return self._ejecutar_bloqueado()

    def _ejecutar_bloqueado(self) -> ResultadoIndexarConocimiento:
        documentos = self._repositorio_conocimiento.listar_todos()
        indexados: list[DocumentoConocimiento] = []
        total_fragmentos = 0
        for documento in documentos:
            fragmentos = self._indexar_documento(documento)
            total_fragmentos += len(fragmentos)
            documento.cantidad_fragmentos = len(fragmentos)
            self._repositorio_conocimiento.actualizar_cantidad_fragmentos(
                documento.id, len(fragmentos)
            )
            indexados.append(documento)
        return ResultadoIndexarConocimiento(
            documentos_indexados=len(indexados),
            total_fragmentos=total_fragmentos,
            documentos=tuple(
                documento_a_resultado(item, estado="indexed") for item in indexados
            ),
        )

    def _indexar_documento(
        self, documento: DocumentoConocimiento
    ) -> list[FragmentoDocumento]:
        contenido = self._repositorio_conocimiento.leer_contenido(documento)
        if HashContenido.desde_contenido(contenido) != documento.hash_contenido:
            raise ErrorDocumentoConocimientoInvalido("El contenido cambió; no se puede reindexar")
        fragmentos = self._fragmentador.fragmentar(contenido, documento)
        if not fragmentos:
            raise ErrorDocumentoConocimientoInvalido("El documento no contiene fragmentos")
        catalogo = [FragmentoCatalogo(f.fragmento_id, f.contenido, f.indice_fragmento) for f in fragmentos]
        ids = self._repositorio_conocimiento.preparar_fragmentos(documento.id, catalogo)
        embeddings = self._embedding_port.embed_texts(
            [fragmento.contenido for fragmento in fragmentos]
        )
        registros = [
            VectorRecord(
                id=fragmento.fragmento_id,
                embedding=embedding,
                content=fragmento.contenido,
                metadata={
                    "document_id": fragmento.documento_id,
                    "fragment_id": fragmento_uuid,
                    "document_title": fragmento.titulo,
                    "topic": fragmento.tema,
                    "content_hash": fragmento.hash_contenido,
                    "chunk_index": fragmento.indice_fragmento,
                    "source_path": fragmento.ruta_origen,
                },
            )
            for fragmento, embedding, fragmento_uuid in zip(fragmentos, embeddings, ids, strict=True)
        ]
        self._almacen_vectores.upsert(registros)
        self._repositorio_conocimiento.confirmar_fragmentos(documento.id, catalogo)
        return fragmentos
