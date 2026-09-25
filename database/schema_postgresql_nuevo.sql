============================================================
-- Base de datos: slm_agricultura_familiar
-- Proyecto: SLM peruano para asistencia técnica a agricultores familiares
-- Motor: PostgreSQL
-- Arquitectura: Hexagonal (la BD pertenece a infraestructura/adaptador de salida)
-- ============================================================

-- Crear base de datos manualmente si se ejecuta desde psql:
-- CREATE DATABASE slm_agricultura_familiar
--   WITH ENCODING 'UTF8'
--   TEMPLATE template0;
-- \c slm_agricultura_familiar

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 1. SEGURIDAD Y USUARIOS
-- ============================================================

CREATE TABLE rol (
    id_rol          BIGSERIAL PRIMARY KEY,
    nombre          VARCHAR(50) NOT NULL UNIQUE,
    descripcion     VARCHAR(255)
);

CREATE TABLE usuario (
    id_usuario      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_rol          BIGINT NOT NULL,
    nombre          VARCHAR(120) NOT NULL,
    email           VARCHAR(150) NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    estado          VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    fecha_registro  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultimo_acceso   TIMESTAMPTZ,
    CONSTRAINT fk_usuario_rol
        FOREIGN KEY (id_rol) REFERENCES rol(id_rol)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT ck_usuario_estado
        CHECK (estado IN ('ACTIVO', 'INACTIVO', 'BLOQUEADO'))
);

CREATE TABLE agricultor (
    id_agricultor   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_usuario      UUID NOT NULL UNIQUE,
    nombre_completo VARCHAR(150) NOT NULL,
    telefono        VARCHAR(30),
    ubicacion       VARCHAR(200),
    experiencia_anios SMALLINT,
    CONSTRAINT fk_agricultor_usuario
        FOREIGN KEY (id_usuario) REFERENCES usuario(id_usuario)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_agricultor_experiencia
        CHECK (experiencia_anios IS NULL OR experiencia_anios >= 0)
);

CREATE TABLE perfil_agricola (
    id_perfil       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_agricultor   UUID NOT NULL UNIQUE,
    tipo_agricultura VARCHAR(100),
    superficie_total NUMERIC(10,2),
    region          VARCHAR(100),
    tipo_suelo      VARCHAR(100),
    sistema_riego   VARCHAR(100),
    observaciones   TEXT,
    CONSTRAINT fk_perfil_agricultor
        FOREIGN KEY (id_agricultor) REFERENCES agricultor(id_agricultor)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_superficie_total
        CHECK (superficie_total IS NULL OR superficie_total >= 0)
);

-- ============================================================
-- 2. CONTEXTO AGRÍCOLA
-- ============================================================

CREATE TABLE parcela (
    id_parcela      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_agricultor   UUID NOT NULL,
    nombre          VARCHAR(120),
    ubicacion       VARCHAR(200) NOT NULL,
    superficie      NUMERIC(10,2),
    tipo_suelo      VARCHAR(100),
    altitud         NUMERIC(8,2),
    observaciones   TEXT,
    CONSTRAINT fk_parcela_agricultor
        FOREIGN KEY (id_agricultor) REFERENCES agricultor(id_agricultor)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_parcela_superficie
        CHECK (superficie IS NULL OR superficie >= 0)
);

CREATE TABLE cultivo (
    id_cultivo      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_parcela      UUID NOT NULL,
    nombre_comun    VARCHAR(120) NOT NULL,
    nombre_cientifico VARCHAR(180),
    fecha_siembra   DATE,
    fecha_cosecha   DATE,
    estado          VARCHAR(50),
    observaciones   TEXT,
    CONSTRAINT fk_cultivo_parcela
        FOREIGN KEY (id_parcela) REFERENCES parcela(id_parcela)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_fechas_cultivo
        CHECK (fecha_cosecha IS NULL OR fecha_siembra IS NULL OR fecha_cosecha >= fecha_siembra)
);

CREATE TABLE registro_cultivo (
    id_registro     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_cultivo      UUID NOT NULL,
    tipo_registro   VARCHAR(80) NOT NULL,
    fecha_registro  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valor           NUMERIC(14,4),
    unidad          VARCHAR(40),
    observaciones   TEXT,
    CONSTRAINT fk_registro_cultivo
        FOREIGN KEY (id_cultivo) REFERENCES cultivo(id_cultivo)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

-- ============================================================
-- 3. CONSULTAS E IA
-- ============================================================

CREATE TABLE consulta (
    id_consulta     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_agricultor   UUID NOT NULL,
    id_cultivo      UUID,
    pregunta        TEXT NOT NULL,
    fecha_consulta  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    estado          VARCHAR(30) NOT NULL DEFAULT 'RECIBIDA',
    CONSTRAINT fk_consulta_agricultor
        FOREIGN KEY (id_agricultor) REFERENCES agricultor(id_agricultor)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_consulta_cultivo
        FOREIGN KEY (id_cultivo) REFERENCES cultivo(id_cultivo)
        ON UPDATE CASCADE
        ON DELETE SET NULL,
    CONSTRAINT ck_consulta_estado
        CHECK (estado IN ('RECIBIDA', 'PROCESANDO', 'RESPONDIDA', 'ERROR'))
);

CREATE TABLE clasificacion (
    id_clasificacion UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_consulta      UUID NOT NULL UNIQUE,
    categoria        VARCHAR(120) NOT NULL,
    subcategoria     VARCHAR(120),
    confianza        NUMERIC(5,4),
    modelo_version   VARCHAR(100),
    fecha_clasificacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_clasificacion_consulta
        FOREIGN KEY (id_consulta) REFERENCES consulta(id_consulta)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_clasificacion_confianza
        CHECK (confianza IS NULL OR (confianza >= 0 AND confianza <= 1))
);

CREATE TABLE respuesta (
    id_respuesta     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_consulta      UUID NOT NULL UNIQUE,
    respuesta_generada TEXT NOT NULL,
    advertencia      TEXT,
    fecha_respuesta  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modelo_utilizado VARCHAR(120),
    tiempo_generacion_ms INTEGER,
    CONSTRAINT fk_respuesta_consulta
        FOREIGN KEY (id_consulta) REFERENCES consulta(id_consulta)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_tiempo_generacion
        CHECK (tiempo_generacion_ms IS NULL OR tiempo_generacion_ms >= 0)
);

CREATE TABLE prediccion_riesgo (
    id_riesgo        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_respuesta     UUID NOT NULL UNIQUE,
    nivel_riesgo     VARCHAR(20) NOT NULL,
    probabilidad     NUMERIC(5,4),
    factores_detectados TEXT,
    recomendaciones TEXT,
    modelo_version  VARCHAR(100),
    fecha_prediccion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_riesgo_respuesta
        FOREIGN KEY (id_respuesta) REFERENCES respuesta(id_respuesta)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_nivel_riesgo
        CHECK (nivel_riesgo IN ('BAJO', 'MEDIO', 'ALTO')),
    CONSTRAINT ck_riesgo_probabilidad
        CHECK (probabilidad IS NULL OR (probabilidad >= 0 AND probabilidad <= 1))
);

-- Tabla opcional de apoyo al historial mostrado en la interfaz.
-- El historial también puede derivarse de consulta + respuesta.
CREATE TABLE historial_consulta (
    id_historial     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_agricultor    UUID NOT NULL,
    id_consulta      UUID NOT NULL UNIQUE,
    fecha_consulta   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_historial_agricultor
        FOREIGN KEY (id_agricultor) REFERENCES agricultor(id_agricultor)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_historial_consulta
        FOREIGN KEY (id_consulta) REFERENCES consulta(id_consulta)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

-- ============================================================
-- 4. BASE DE CONOCIMIENTO / RAG
-- ============================================================

CREATE TABLE documento (
    id_documento     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    titulo           VARCHAR(255) NOT NULL,
    tipo_documento   VARCHAR(80),
    fuente           VARCHAR(150) NOT NULL,
    autor            VARCHAR(200),
    fecha_publicacion DATE,
    url              TEXT,
    ruta_archivo     TEXT,
    fecha_ingreso    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    estado           VARCHAR(20) NOT NULL DEFAULT 'ACTIVO',
    CONSTRAINT ck_documento_estado
        CHECK (estado IN ('ACTIVO', 'INACTIVO', 'BORRADOR'))
);

CREATE TABLE fragmento (
    id_fragmento     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_documento     UUID NOT NULL,
    contenido        TEXT NOT NULL,
    vector_id        VARCHAR(150),
    pagina           INTEGER,
    seccion          VARCHAR(180),
    orden_fragmento  INTEGER,
    CONSTRAINT fk_fragmento_documento
        FOREIGN KEY (id_documento) REFERENCES documento(id_documento)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT ck_fragmento_pagina
        CHECK (pagina IS NULL OR pagina > 0)
);

CREATE TABLE fuente_utilizada (
    id_fuente_uso    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_respuesta     UUID NOT NULL,
    id_documento     UUID NOT NULL,
    id_fragmento     UUID,
    relevancia       NUMERIC(6,5),
    url_referencia   TEXT,
    CONSTRAINT fk_fuente_respuesta
        FOREIGN KEY (id_respuesta) REFERENCES respuesta(id_respuesta)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    CONSTRAINT fk_fuente_documento
        FOREIGN KEY (id_documento) REFERENCES documento(id_documento)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_fuente_fragmento
        FOREIGN KEY (id_fragmento) REFERENCES fragmento(id_fragmento)
        ON UPDATE CASCADE
        ON DELETE SET NULL,
    CONSTRAINT ck_fuente_relevancia
        CHECK (relevancia IS NULL OR (relevancia >= 0 AND relevancia <= 1)),
    CONSTRAINT uq_fuente_respuesta_fragmento
        UNIQUE (id_respuesta, id_fragmento)
);

-- ============================================================
-- 5. ÍNDICES
-- ============================================================

CREATE INDEX idx_usuario_rol
    ON usuario(id_rol);

CREATE INDEX idx_agricultor_usuario
    ON agricultor(id_usuario);

CREATE INDEX idx_parcela_agricultor
    ON parcela(id_agricultor);

CREATE INDEX idx_cultivo_parcela
    ON cultivo(id_parcela);

CREATE INDEX idx_registro_cultivo_fecha
    ON registro_cultivo(id_cultivo, fecha_registro DESC);

CREATE INDEX idx_consulta_agricultor_fecha
    ON consulta(id_agricultor, fecha_consulta DESC);

CREATE INDEX idx_consulta_cultivo
    ON consulta(id_cultivo);

CREATE INDEX idx_consulta_estado
    ON consulta(estado);

CREATE INDEX idx_documento_fuente
    ON documento(fuente);

CREATE INDEX idx_documento_estado
    ON documento(estado);

CREATE INDEX idx_fragmento_documento
    ON fragmento(id_documento);

CREATE INDEX idx_fuente_respuesta
    ON fuente_utilizada(id_respuesta);

CREATE INDEX idx_historial_agricultor_fecha
    ON historial_consulta(id_agricultor, fecha_consulta DESC);

-- ============================================================
-- 6. DATOS INICIALES
-- ============================================================

INSERT INTO rol (nombre, descripcion)
VALUES
    ('AGRICULTOR', 'Usuario agricultor que realiza consultas y revisa orientaciones'),
    ('ADMINISTRADOR', 'Usuario responsable de la gestión documental y administración')
ON CONFLICT (nombre) DO NOTHING;

-- ============================================================
-- NOTAS DE ARQUITECTURA
-- ============================================================
-- 1. PostgreSQL almacena datos transaccionales y metadatos.
-- 2. FAISS mantiene el índice vectorial; fragmento.vector_id referencia
--    conceptualmente el identificador usado por dicho índice.
-- 3. Los modelos ML, RAG y Ollama/SLM no son tablas de la BD:
--    se integran mediante puertos y adaptadores de la arquitectura hexagonal.
-- 4. Las contraseñas nunca deben almacenarse en texto plano.
-- 5. La aplicación debe aplicar autorización por rol y HTTPS.
