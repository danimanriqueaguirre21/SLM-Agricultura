-- STORED ROUTINES PMV1
-- Base de datos: slm_agricultura_familiar
-- PostgreSQL 17+
-- HU-01 a HU-06
-- NOTA: password_hash llega ya hasheado desde backend.
-- FAISS realiza la búsqueda vectorial; PostgreSQL conserva metadatos, fragmentos y trazabilidad.
-- Requiere el DDL actualizado de schema_postgresql_nuevo.sql.
-- Las funciones de listado y detalle amplían RETURNS TABLE. Si ya están
-- instaladas con la firma de retorno anterior, requieren una migración explícita
-- que revise dependencias y las recree; CREATE OR REPLACE no cambia ese retorno.

BEGIN;

-- HU-01 REGISTRO
CREATE OR REPLACE FUNCTION sp_registrar_agricultor(
    p_nombre VARCHAR,
    p_email VARCHAR,
    p_password_hash TEXT,
    p_telefono VARCHAR DEFAULT NULL,
    p_ubicacion VARCHAR DEFAULT NULL,
    p_experiencia_anios SMALLINT DEFAULT NULL
)
RETURNS TABLE(id_usuario UUID, id_agricultor UUID)
LANGUAGE plpgsql
AS $$
DECLARE
    v_id_rol BIGINT;
    v_id_usuario UUID;
    v_id_agricultor UUID;
BEGIN
    IF NULLIF(BTRIM(p_nombre), '') IS NULL THEN
        RAISE EXCEPTION 'El nombre es obligatorio';
    END IF;
    IF NULLIF(BTRIM(p_email), '') IS NULL THEN
        RAISE EXCEPTION 'El correo es obligatorio';
    END IF;
    IF NULLIF(BTRIM(p_password_hash), '') IS NULL THEN
        RAISE EXCEPTION 'El hash de contraseña es obligatorio';
    END IF;
    IF p_experiencia_anios IS NOT NULL AND p_experiencia_anios < 0 THEN
        RAISE EXCEPTION 'Los años de experiencia no pueden ser negativos';
    END IF;
    IF EXISTS (SELECT 1 FROM usuario WHERE LOWER(email)=LOWER(BTRIM(p_email))) THEN
        RAISE EXCEPTION 'Ya existe un usuario registrado con ese correo';
    END IF;

    SELECT id_rol INTO v_id_rol FROM rol WHERE nombre='AGRICULTOR';
    IF v_id_rol IS NULL THEN
        INSERT INTO rol(nombre, descripcion)
        VALUES ('AGRICULTOR','Usuario agricultor')
        RETURNING id_rol INTO v_id_rol;
    END IF;

    INSERT INTO usuario(id_rol,nombre,email,password_hash,estado)
    VALUES(v_id_rol,BTRIM(p_nombre),LOWER(BTRIM(p_email)),p_password_hash,'ACTIVO')
    RETURNING usuario.id_usuario INTO v_id_usuario;

    INSERT INTO agricultor(id_usuario,nombre_completo,telefono,ubicacion,experiencia_anios)
    VALUES(v_id_usuario,BTRIM(p_nombre),NULLIF(BTRIM(p_telefono),''),
           NULLIF(BTRIM(p_ubicacion),''),p_experiencia_anios)
    RETURNING agricultor.id_agricultor INTO v_id_agricultor;

    RETURN QUERY SELECT v_id_usuario, v_id_agricultor;
END;
$$;

-- HU-02 LOGIN
CREATE OR REPLACE FUNCTION sp_obtener_usuario_login(p_email VARCHAR)
RETURNS TABLE(
    id_usuario UUID,
    id_agricultor UUID,
    id_rol BIGINT,
    rol VARCHAR,
    nombre VARCHAR,
    email VARCHAR,
    password_hash TEXT,
    estado VARCHAR
)
LANGUAGE sql
AS $$
    SELECT u.id_usuario,a.id_agricultor,u.id_rol,r.nombre,u.nombre,u.email,u.password_hash,u.estado
    FROM usuario u
    JOIN rol r ON r.id_rol=u.id_rol
    LEFT JOIN agricultor a ON a.id_usuario=u.id_usuario
    WHERE LOWER(u.email)=LOWER(BTRIM(p_email))
    LIMIT 1;
$$;

CREATE OR REPLACE PROCEDURE sp_actualizar_ultimo_acceso(p_id_usuario UUID)
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE usuario
       SET ultimo_acceso=CURRENT_TIMESTAMP
     WHERE id_usuario=p_id_usuario AND estado='ACTIVO';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Usuario no encontrado o no activo';
    END IF;
END;
$$;

-- HU-03 CONTEXTO Y CULTIVO
CREATE OR REPLACE FUNCTION sp_registrar_parcela(
    p_id_agricultor UUID,
    p_nombre VARCHAR,
    p_ubicacion VARCHAR,
    p_superficie NUMERIC DEFAULT NULL,
    p_tipo_suelo VARCHAR DEFAULT NULL,
    p_altitud NUMERIC DEFAULT NULL,
    p_observaciones TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE v_id UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM agricultor WHERE id_agricultor=p_id_agricultor) THEN
        RAISE EXCEPTION 'Agricultor no encontrado';
    END IF;
    IF NULLIF(BTRIM(p_ubicacion),'') IS NULL THEN
        RAISE EXCEPTION 'La ubicación es obligatoria';
    END IF;

    INSERT INTO parcela(id_agricultor,nombre,ubicacion,superficie,tipo_suelo,altitud,observaciones)
    VALUES(p_id_agricultor,NULLIF(BTRIM(p_nombre),''),BTRIM(p_ubicacion),p_superficie,
           NULLIF(BTRIM(p_tipo_suelo),''),p_altitud,NULLIF(BTRIM(p_observaciones),''))
    RETURNING id_parcela INTO v_id;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION sp_registrar_cultivo(
    p_id_parcela UUID,
    p_nombre_comun VARCHAR,
    p_nombre_cientifico VARCHAR DEFAULT NULL,
    p_fecha_siembra DATE DEFAULT NULL,
    p_fecha_cosecha DATE DEFAULT NULL,
    p_estado VARCHAR DEFAULT 'ACTIVO',
    p_observaciones TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_id UUID;
    v_id_agricultor UUID;
BEGIN
    SELECT p.id_agricultor INTO v_id_agricultor
    FROM parcela p
    WHERE p.id_parcela=p_id_parcela
    FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Parcela no encontrada';
    END IF;
    IF NULLIF(BTRIM(p_nombre_comun),'') IS NULL THEN
        RAISE EXCEPTION 'El nombre del cultivo es obligatorio';
    END IF;

    INSERT INTO cultivo(id_parcela,id_agricultor,nombre_comun,nombre_cientifico,fecha_siembra,fecha_cosecha,estado,observaciones)
    VALUES(p_id_parcela,v_id_agricultor,BTRIM(p_nombre_comun),NULLIF(BTRIM(p_nombre_cientifico),''),
           p_fecha_siembra,p_fecha_cosecha,NULLIF(BTRIM(p_estado),''),
           NULLIF(BTRIM(p_observaciones),''))
    RETURNING id_cultivo INTO v_id;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION sp_listar_cultivos_agricultor(p_id_agricultor UUID)
RETURNS TABLE(
    id_cultivo UUID,
    nombre_comun VARCHAR,
    nombre_cientifico VARCHAR,
    estado VARCHAR,
    id_parcela UUID,
    parcela VARCHAR,
    ubicacion VARCHAR,
    tipo_suelo VARCHAR,
    altitud NUMERIC,
    observaciones TEXT,
    fecha_creacion TIMESTAMPTZ,
    esta_seleccionado BOOLEAN
)
LANGUAGE sql
AS $$
    SELECT c.id_cultivo,c.nombre_comun,c.nombre_cientifico,c.estado,
           p.id_parcela,p.nombre,p.ubicacion,p.tipo_suelo,p.altitud,
           c.observaciones,c.fecha_creacion,
           COALESCE(a.id_cultivo_seleccionado=c.id_cultivo,FALSE)
    FROM cultivo c
    JOIN parcela p ON p.id_parcela=c.id_parcela AND p.id_agricultor=c.id_agricultor
    JOIN agricultor a ON a.id_agricultor=c.id_agricultor
    WHERE c.id_agricultor=p_id_agricultor
    ORDER BY c.fecha_creacion DESC,c.id_cultivo;
$$;

CREATE OR REPLACE FUNCTION sp_obtener_contexto_cultivo(p_id_agricultor UUID,p_id_cultivo UUID)
RETURNS TABLE(
    id_cultivo UUID,
    nombre_comun VARCHAR,
    nombre_cientifico VARCHAR,
    estado_cultivo VARCHAR,
    id_parcela UUID,
    parcela VARCHAR,
    ubicacion VARCHAR,
    superficie NUMERIC,
    tipo_suelo VARCHAR,
    altitud NUMERIC,
    observaciones TEXT,
    fecha_creacion TIMESTAMPTZ,
    esta_seleccionado BOOLEAN
)
LANGUAGE sql
AS $$
    SELECT c.id_cultivo,c.nombre_comun,c.nombre_cientifico,c.estado,
           p.id_parcela,p.nombre,p.ubicacion,p.superficie,p.tipo_suelo,p.altitud,
           c.observaciones,c.fecha_creacion,
           COALESCE(a.id_cultivo_seleccionado=c.id_cultivo,FALSE)
    FROM cultivo c
    JOIN parcela p ON p.id_parcela=c.id_parcela AND p.id_agricultor=c.id_agricultor
    JOIN agricultor a ON a.id_agricultor=c.id_agricultor
    WHERE c.id_cultivo=p_id_cultivo
      AND c.id_agricultor=p_id_agricultor
    LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION sp_seleccionar_cultivo(
    p_id_agricultor UUID,
    p_id_cultivo UUID
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_id_agricultor IS NULL OR p_id_cultivo IS NULL THEN
        RAISE EXCEPTION 'El agricultor y el cultivo son obligatorios'
            USING ERRCODE = '22004';
    END IF;

    -- Las selecciones concurrentes actualizan la misma fila del agricultor.
    -- La FK compuesta garantiza pertenencia incluso fuera de esta función.
    UPDATE agricultor a
       SET id_cultivo_seleccionado=p_id_cultivo
     WHERE a.id_agricultor=p_id_agricultor
       AND EXISTS (
           SELECT 1 FROM cultivo c
           WHERE c.id_cultivo=p_id_cultivo
             AND c.id_agricultor=a.id_agricultor
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Cultivo no encontrado para el agricultor'
            USING ERRCODE = 'P0002';
    END IF;

    RETURN p_id_cultivo;
END;
$$;

CREATE OR REPLACE FUNCTION sp_obtener_contexto_seleccionado(p_id_agricultor UUID)
RETURNS TABLE(
    id_cultivo UUID,
    nombre_comun VARCHAR,
    nombre_cientifico VARCHAR,
    estado_cultivo VARCHAR,
    id_parcela UUID,
    parcela VARCHAR,
    ubicacion VARCHAR,
    superficie NUMERIC,
    tipo_suelo VARCHAR,
    altitud NUMERIC,
    observaciones TEXT,
    fecha_creacion TIMESTAMPTZ,
    esta_seleccionado BOOLEAN
)
LANGUAGE sql
AS $$
    SELECT contexto.*
    FROM agricultor a
    CROSS JOIN LATERAL sp_obtener_contexto_cultivo(
        a.id_agricultor,a.id_cultivo_seleccionado
    ) AS contexto
    WHERE a.id_agricultor=p_id_agricultor
      AND a.id_cultivo_seleccionado IS NOT NULL;
$$;

-- HU-04 CONSULTA AGRÍCOLA
CREATE OR REPLACE FUNCTION sp_crear_consulta(
    p_id_agricultor UUID,
    p_id_cultivo UUID,
    p_pregunta TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE v_id UUID;
BEGIN
    IF NULLIF(BTRIM(p_pregunta),'') IS NULL THEN
        RAISE EXCEPTION 'La consulta no puede estar vacía';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM agricultor WHERE id_agricultor=p_id_agricultor) THEN
        RAISE EXCEPTION 'Agricultor no encontrado';
    END IF;

    IF p_id_cultivo IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM cultivo c
        JOIN parcela p ON p.id_parcela=c.id_parcela
        WHERE c.id_cultivo=p_id_cultivo
          AND p.id_agricultor=p_id_agricultor
    ) THEN
        RAISE EXCEPTION 'El cultivo no pertenece al agricultor';
    END IF;

    INSERT INTO consulta(id_agricultor,id_cultivo,pregunta,estado)
    VALUES(p_id_agricultor,p_id_cultivo,BTRIM(p_pregunta),'RECIBIDA')
    RETURNING id_consulta INTO v_id;

    RETURN v_id;
END;
$$;

CREATE OR REPLACE PROCEDURE sp_actualizar_estado_consulta(p_id_consulta UUID,p_estado VARCHAR)
LANGUAGE plpgsql
AS $$
BEGIN
    IF UPPER(BTRIM(p_estado)) NOT IN ('RECIBIDA','PROCESANDO','RESPONDIDA','ERROR') THEN
        RAISE EXCEPTION 'Estado no válido';
    END IF;
    UPDATE consulta SET estado=UPPER(BTRIM(p_estado)) WHERE id_consulta=p_id_consulta;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Consulta no encontrada';
    END IF;
END;
$$;

-- HU-05 BASE DE CONOCIMIENTO
CREATE OR REPLACE FUNCTION sp_registrar_documento(
    p_titulo VARCHAR,
    p_tipo_documento VARCHAR,
    p_fuente VARCHAR,
    p_autor VARCHAR DEFAULT NULL,
    p_fecha_publicacion DATE DEFAULT NULL,
    p_url TEXT DEFAULT NULL,
    p_ruta_archivo TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE v_id UUID;
BEGIN
    IF NULLIF(BTRIM(p_titulo),'') IS NULL THEN
        RAISE EXCEPTION 'El título es obligatorio';
    END IF;
    IF NULLIF(BTRIM(p_fuente),'') IS NULL THEN
        RAISE EXCEPTION 'La fuente es obligatoria';
    END IF;

    INSERT INTO documento(titulo,tipo_documento,fuente,autor,fecha_publicacion,url,ruta_archivo,estado)
    VALUES(BTRIM(p_titulo),NULLIF(BTRIM(p_tipo_documento),''),BTRIM(p_fuente),
           NULLIF(BTRIM(p_autor),''),p_fecha_publicacion,NULLIF(BTRIM(p_url),''),
           NULLIF(BTRIM(p_ruta_archivo),''),'ACTIVO')
    RETURNING id_documento INTO v_id;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION sp_registrar_fragmento(
    p_id_documento UUID,
    p_contenido TEXT,
    p_vector_id VARCHAR DEFAULT NULL,
    p_pagina INTEGER DEFAULT NULL,
    p_seccion VARCHAR DEFAULT NULL,
    p_orden_fragmento INTEGER DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE v_id UUID;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM documento
        WHERE id_documento=p_id_documento AND estado='ACTIVO'
    ) THEN
        RAISE EXCEPTION 'Documento activo no encontrado';
    END IF;

    IF NULLIF(BTRIM(p_contenido),'') IS NULL THEN
        RAISE EXCEPTION 'El fragmento no puede estar vacío';
    END IF;

    INSERT INTO fragmento(id_documento,contenido,vector_id,pagina,seccion,orden_fragmento)
    VALUES(p_id_documento,p_contenido,NULLIF(BTRIM(p_vector_id),''),
           p_pagina,NULLIF(BTRIM(p_seccion),''),p_orden_fragmento)
    RETURNING id_fragmento INTO v_id;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE PROCEDURE sp_actualizar_vector_fragmento(p_id_fragmento UUID,p_vector_id VARCHAR)
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE fragmento
       SET vector_id=NULLIF(BTRIM(p_vector_id),'')
     WHERE id_fragmento=p_id_fragmento;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Fragmento no encontrado';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION sp_listar_documentos_activos()
RETURNS TABLE(
    id_documento UUID,
    titulo VARCHAR,
    tipo_documento VARCHAR,
    fuente VARCHAR,
    autor VARCHAR,
    fecha_publicacion DATE,
    url TEXT,
    ruta_archivo TEXT,
    fecha_ingreso TIMESTAMPTZ
)
LANGUAGE sql
AS $$
    SELECT id_documento,titulo,tipo_documento,fuente,autor,fecha_publicacion,url,ruta_archivo,fecha_ingreso
    FROM documento
    WHERE estado='ACTIVO'
    ORDER BY fecha_ingreso DESC;
$$;

-- HU-06 RAG BÁSICO
CREATE OR REPLACE FUNCTION sp_obtener_fragmentos_por_vector_ids(p_vector_ids TEXT[])
RETURNS TABLE(
    id_fragmento UUID,
    vector_id VARCHAR,
    contenido TEXT,
    pagina INTEGER,
    seccion VARCHAR,
    id_documento UUID,
    titulo_documento VARCHAR,
    fuente VARCHAR,
    autor VARCHAR,
    url TEXT
)
LANGUAGE sql
AS $$
    SELECT f.id_fragmento,f.vector_id,f.contenido,f.pagina,f.seccion,
           d.id_documento,d.titulo,d.fuente,d.autor,d.url
    FROM fragmento f
    JOIN documento d ON d.id_documento=f.id_documento
    WHERE f.vector_id = ANY(p_vector_ids)
      AND d.estado='ACTIVO';
$$;

CREATE OR REPLACE FUNCTION sp_guardar_respuesta_rag(
    p_id_consulta UUID,
    p_respuesta_generada TEXT,
    p_advertencia TEXT DEFAULT NULL,
    p_modelo_utilizado VARCHAR DEFAULT NULL,
    p_tiempo_generacion_ms INTEGER DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE v_id UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM consulta WHERE id_consulta=p_id_consulta) THEN
        RAISE EXCEPTION 'Consulta no encontrada';
    END IF;

    INSERT INTO respuesta(id_consulta,respuesta_generada,advertencia,modelo_utilizado,tiempo_generacion_ms)
    VALUES(p_id_consulta,p_respuesta_generada,NULLIF(BTRIM(p_advertencia),''),
           NULLIF(BTRIM(p_modelo_utilizado),''),p_tiempo_generacion_ms)
    ON CONFLICT (id_consulta)
    DO UPDATE SET
        respuesta_generada=EXCLUDED.respuesta_generada,
        advertencia=EXCLUDED.advertencia,
        fecha_respuesta=CURRENT_TIMESTAMP,
        modelo_utilizado=EXCLUDED.modelo_utilizado,
        tiempo_generacion_ms=EXCLUDED.tiempo_generacion_ms
    RETURNING id_respuesta INTO v_id;

    UPDATE consulta SET estado='RESPONDIDA' WHERE id_consulta=p_id_consulta;
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION sp_registrar_fuente_utilizada(
    p_id_respuesta UUID,
    p_id_documento UUID,
    p_id_fragmento UUID DEFAULT NULL,
    p_relevancia NUMERIC DEFAULT NULL,
    p_url_referencia TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE v_id UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM respuesta WHERE id_respuesta=p_id_respuesta) THEN
        RAISE EXCEPTION 'Respuesta no encontrada';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM documento WHERE id_documento=p_id_documento) THEN
        RAISE EXCEPTION 'Documento no encontrado';
    END IF;

    INSERT INTO fuente_utilizada(id_respuesta,id_documento,id_fragmento,relevancia,url_referencia)
    VALUES(p_id_respuesta,p_id_documento,p_id_fragmento,p_relevancia,NULLIF(BTRIM(p_url_referencia),''))
    ON CONFLICT (id_respuesta,id_fragmento)
    DO UPDATE SET relevancia=EXCLUDED.relevancia,
                  url_referencia=EXCLUDED.url_referencia
    RETURNING id_fuente_uso INTO v_id;

    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION sp_obtener_resultado_consulta(
    p_id_consulta UUID,
    p_id_agricultor UUID
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE v_json JSONB;
BEGIN
    SELECT jsonb_build_object(
        'consulta', jsonb_build_object(
            'id_consulta',c.id_consulta,
            'pregunta',c.pregunta,
            'fecha_consulta',c.fecha_consulta,
            'estado',c.estado,
            'cultivo',cu.nombre_comun,
            'ubicacion',p.ubicacion
        ),
        'respuesta', CASE WHEN r.id_respuesta IS NULL THEN NULL ELSE jsonb_build_object(
            'id_respuesta',r.id_respuesta,
            'texto',r.respuesta_generada,
            'advertencia',r.advertencia,
            'fecha_respuesta',r.fecha_respuesta,
            'modelo',r.modelo_utilizado,
            'tiempo_generacion_ms',r.tiempo_generacion_ms
        ) END,
        'fuentes', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id_fuente_uso',fu.id_fuente_uso,
                'documento',d.titulo,
                'institucion',d.fuente,
                'id_fragmento',fu.id_fragmento,
                'pagina',fr.pagina,
                'seccion',fr.seccion,
                'relevancia',fu.relevancia,
                'url',COALESCE(fu.url_referencia,d.url)
            ) ORDER BY fu.relevancia DESC NULLS LAST)
            FROM fuente_utilizada fu
            JOIN documento d ON d.id_documento=fu.id_documento
            LEFT JOIN fragmento fr ON fr.id_fragmento=fu.id_fragmento
            WHERE fu.id_respuesta=r.id_respuesta
        ), '[]'::jsonb)
    )
    INTO v_json
    FROM consulta c
    LEFT JOIN cultivo cu ON cu.id_cultivo=c.id_cultivo
    LEFT JOIN parcela p ON p.id_parcela=cu.id_parcela
    LEFT JOIN respuesta r ON r.id_consulta=c.id_consulta
    WHERE c.id_consulta=p_id_consulta
      AND c.id_agricultor=p_id_agricultor;

    IF v_json IS NULL THEN
        RAISE EXCEPTION 'Consulta no encontrada para el agricultor';
    END IF;

    RETURN v_json;
END;
$$;

COMMIT;
