from app.application.services.fragmentador_documentos import FragmentadorDocumentos
from app.application.services.servicio_recuperacion_rag import ServicioRecuperacionRag
from app.application.useCases.crear_contexto_agricola import CrearContextoAgricola
from app.application.useCases.incorporar_conocimiento import IncorporarConocimiento
from app.application.useCases.indexar_conocimiento import IndexarConocimiento
from app.application.useCases.iniciar_sesion_agricultor import IniciarSesionAgricultor
from app.application.useCases.listar_contextos_agricolas import ListarContextosAgricolas
from app.application.useCases.listar_documentos_conocimiento import ListarDocumentosConocimiento
from app.application.useCases.registrar_agricultor import RegistrarAgricultor
from app.application.useCases.registrar_consulta import RegistrarConsulta
from app.application.useCases.seleccionar_contexto_agricola import SeleccionarContextoAgricola
from app.domain.ports.input.gestionar_contexto_port import (
    PuertoCrearContextoAgricola,
    PuertoListarContextosAgricolas,
    PuertoSeleccionarContextoAgricola,
)
from app.domain.ports.input.incorporar_conocimiento_port import (
    PuertoIncorporarConocimiento,
    PuertoListarDocumentosConocimiento,
)
from app.domain.ports.input.indexar_conocimiento_port import PuertoIndexarConocimiento
from app.domain.ports.input.iniciar_sesion_agricultor_port import PuertoIniciarSesionAgricultor
from app.domain.ports.input.registrar_agricultor_port import PuertoRegistrarAgricultor
from app.domain.ports.input.registrar_consulta_port import PuertoRegistrarConsulta
from app.domain.ports.output.embedding_port import EmbeddingPort
from app.domain.ports.output.hasher_contrasena_port import PuertoHasherContrasena
from app.domain.ports.output.repositorio_agricultor_port import PuertoRepositorioAgricultor
from app.domain.ports.output.repositorio_consulta_port import PuertoRepositorioConsulta
from app.domain.ports.output.repositorio_contexto_agricola_port import (
    PuertoRepositorioContextoAgricola,
)
from app.domain.ports.output.repositorio_documento_conocimiento_port import (
    PuertoRepositorioDocumentoConocimiento,
)
from app.domain.ports.output.repositorio_evidencia_port import PuertoRepositorioEvidencia
from app.domain.ports.output.puerto_observaciones_meteorologicas import (
    PuertoObservacionesMeteorologicas,
)
from app.domain.ports.output.text_generation_port import PuertoGeneracionTexto
from app.domain.ports.output.token_issuer_port import PuertoEmisorToken
from app.domain.ports.output.token_verifier_port import PuertoVerificadorToken
from app.domain.ports.output.vector_store_port import VectorStorePort
from app.infrastructure.adapters.output.chroma.chroma_vector_store_adapter import (
    ChromaVectorStoreAdapter,
)
from app.infrastructure.adapters.output.embedding.external_embedding_adapter import (
    ExternalEmbeddingAdapter,
)
from app.infrastructure.adapters.output.embedding.local_lexical_embedding_adapter import (
    LocalLexicalEmbeddingAdapter,
)
from app.infrastructure.adapters.output.generation.adaptador_generacion_ollama import (
    AdaptadorGeneracionOllama,
)
from app.infrastructure.adapters.output.generation.adaptador_generacion_plantilla import (
    AdaptadorGeneracionPlantilla,
)
from app.infrastructure.adapters.output.mysql.connection import create_session_factory
from app.infrastructure.adapters.output.mysql.repositorio_agricultor import (
    RepositorioAgricultorPostgresql,
)
from app.infrastructure.adapters.output.mysql.repositorio_consulta import RepositorioConsultaMysql
from app.infrastructure.adapters.output.mysql.repositorio_contexto_agricola_postgresql import (
    RepositorioContextoAgricolaPostgresql,
)
from app.infrastructure.adapters.output.mysql.repositorio_documento_conocimiento import (
    RepositorioDocumentoConocimientoMysql,
)
from app.infrastructure.adapters.output.mysql.repositorio_evidencia import RepositorioEvidenciaMysql
from app.infrastructure.adapters.output.security.emisor_token_jwt import EmisorTokenJwt
from app.infrastructure.adapters.output.security.hasher_contrasena_bcrypt import (
    HasherContrasenaBcrypt,
)
from app.infrastructure.adapters.output.security.verificador_token_jwt import VerificadorTokenJwt
from app.infrastructure.adapters.output.senamhi.adaptador_senamhi_wis2 import AdaptadorSenamhiWis2
from app.infrastructure.config.settings import Settings, get_settings


class CompositionRoot:
    """Cableado de adaptadores. El dominio no conoce esta clase."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.embedding_port: EmbeddingPort = self._build_embedding_port()
        self.puerto_hasher_contrasena: PuertoHasherContrasena = HasherContrasenaBcrypt()
        self.puerto_emisor_token: PuertoEmisorToken = EmisorTokenJwt(
            secret=self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
            expire_minutes=self.settings.jwt_expire_minutes,
        )
        self.puerto_verificador_token: PuertoVerificadorToken = VerificadorTokenJwt(
            secret=self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
        )
        session_factory = create_session_factory(self.settings)
        self.puerto_repositorio_agricultor: PuertoRepositorioAgricultor = (
            RepositorioAgricultorPostgresql(session_factory)
        )
        self.puerto_repositorio_contexto_agricola: PuertoRepositorioContextoAgricola = (
            RepositorioContextoAgricolaPostgresql(session_factory)
        )
        self.puerto_registrar_agricultor: PuertoRegistrarAgricultor = RegistrarAgricultor(
            repositorio_agricultor=self.puerto_repositorio_agricultor,
            hasher_contrasena=self.puerto_hasher_contrasena,
        )
        self.puerto_iniciar_sesion_agricultor: PuertoIniciarSesionAgricultor = (
            IniciarSesionAgricultor(
                repositorio_agricultor=self.puerto_repositorio_agricultor,
                hasher_contrasena=self.puerto_hasher_contrasena,
                emisor_token=self.puerto_emisor_token,
            )
        )
        self.puerto_crear_contexto_agricola: PuertoCrearContextoAgricola = CrearContextoAgricola(
            self.puerto_repositorio_contexto_agricola
        )
        self.puerto_listar_contextos_agricolas: PuertoListarContextosAgricolas = (
            ListarContextosAgricolas(self.puerto_repositorio_contexto_agricola)
        )
        self.puerto_seleccionar_contexto_agricola: PuertoSeleccionarContextoAgricola = (
            SeleccionarContextoAgricola(self.puerto_repositorio_contexto_agricola)
        )
        self.puerto_generacion_texto: PuertoGeneracionTexto = self._build_generation_port()
        self.puerto_observaciones_meteorologicas: PuertoObservacionesMeteorologicas = (
            AdaptadorSenamhiWis2(
                base_url=self.settings.senamhi_wis2_base_url,
                coleccion=self.settings.senamhi_wis2_collection,
                timeout_seconds=self.settings.senamhi_wis2_timeout_seconds,
            )
        )
        self.puerto_repositorio_consulta: PuertoRepositorioConsulta = RepositorioConsultaMysql(
            session_factory
        )
        self.puerto_repositorio_evidencia: PuertoRepositorioEvidencia = RepositorioEvidenciaMysql(
            session_factory
        )
        self.puerto_almacen_vectores: VectorStorePort = ChromaVectorStoreAdapter(
            persist_dir=self.settings.chroma_persist_dir,
            collection_name=self.settings.chroma_collection,
        )
        self.servicio_recuperacion_rag = ServicioRecuperacionRag(
            embedding_port=self.embedding_port,
            almacen_vectores=self.puerto_almacen_vectores,
            top_k=self.settings.rag_top_k,
            similitud_minima=self.settings.rag_min_similarity,
        )
        self.puerto_registrar_consulta: PuertoRegistrarConsulta = RegistrarConsulta(
            repositorio_consulta=self.puerto_repositorio_consulta,
            generacion_texto=self.puerto_generacion_texto,
            recuperacion_rag=self.servicio_recuperacion_rag,
            repositorio_evidencia=self.puerto_repositorio_evidencia,
        )
        self.puerto_repositorio_documento_conocimiento: PuertoRepositorioDocumentoConocimiento = (
            RepositorioDocumentoConocimientoMysql(
                session_factory,
                knowledge_dir=self.settings.knowledge_dir,
            )
        )
        self.puerto_incorporar_conocimiento: PuertoIncorporarConocimiento = IncorporarConocimiento(
            self.puerto_repositorio_documento_conocimiento
        )
        self.puerto_listar_documentos_conocimiento: PuertoListarDocumentosConocimiento = (
            ListarDocumentosConocimiento(self.puerto_repositorio_documento_conocimiento)
        )
        self.fragmentador_documentos = FragmentadorDocumentos(max_chars=self.settings.chunk_size)
        self.puerto_indexar_conocimiento: PuertoIndexarConocimiento = IndexarConocimiento(
            repositorio_conocimiento=self.puerto_repositorio_documento_conocimiento,
            embedding_port=self.embedding_port,
            almacen_vectores=self.puerto_almacen_vectores,
            fragmentador=self.fragmentador_documentos,
        )

    def _build_embedding_port(self) -> EmbeddingPort:
        provider = (self.settings.embedding_provider or "local").strip().lower()
        if provider == "external":
            return ExternalEmbeddingAdapter(
                api_url=self.settings.embedding_api_url,
                api_key=self.settings.embedding_api_key,
                model=self.settings.embedding_model,
            )
        return LocalLexicalEmbeddingAdapter(dimension=self.settings.embedding_dimension)

    def _build_generation_port(self) -> PuertoGeneracionTexto:
        provider = (self.settings.generation_provider or "ollama").strip().lower()
        if provider == "template":
            return AdaptadorGeneracionPlantilla()
        if provider != "ollama":
            raise ValueError(
                "GENERATION_PROVIDER debe ser 'ollama' (PMV1) o 'template' (pruebas)."
            )
        return AdaptadorGeneracionOllama(
            base_url=self.settings.ollama_base_url,
            model=self.settings.ollama_model,
            timeout_seconds=self.settings.ollama_timeout_seconds,
        )


def build_container() -> CompositionRoot:
    return CompositionRoot()
