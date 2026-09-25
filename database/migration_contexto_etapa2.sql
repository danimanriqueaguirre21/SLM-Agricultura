-- Etapa 2, alternativa B. PostgreSQL 17+. Ejecutar UNA sola vez.
-- Destino: base existente creada con el DDL y las rutinas anteriores,
-- en el esquema public. Conectarse a la base correcta antes de ejecutar.
-- Ejecutar el archivo completo, con el cliente configurado para detenerse
-- ante errores (en psql: ON_ERROR_STOP=1). No ejecutar bloques por separado.
-- Requiere una ventana de mantenimiento: se bloquean agricultor, parcela
-- y cultivo hasta COMMIT. Si no se obtiene un bloqueo en 10 s, se aborta.
-- Ante un error, efectuar ROLLBACK si el cliente deja la transacción abierta.
-- No elimina tablas ni registros. Los únicos DROP FUNCTION son específicos
-- y RESTRICT: cualquier dependencia no prevista impide la migración.
-- pg_depend no registra todas las referencias dentro de cuerpos SQL/PLpgSQL
-- escritos como texto ni las de clientes externos; revisarlos antes de ejecutar.

BEGIN;
SET LOCAL search_path = public, pg_catalog;
SET LOCAL lock_timeout = '10s';

LOCK TABLE public.agricultor, public.parcela, public.cultivo
    IN ACCESS EXCLUSIVE MODE;

-- Precondiciones y dependencias: fallar antes de cambiar datos o funciones.
-- No se ignoran columnas ya existentes: una segunda ejecución debe fallar.
DO $preflight$
DECLARE
    v_firma TEXT;
    v_oid OID;
    v_dependencias TEXT;
    v_funcion RECORD;
BEGIN
    IF current_setting('server_version_num')::INTEGER < 170000 THEN
        RAISE EXCEPTION 'La migración requiere PostgreSQL 17 o posterior';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE NOT attisdropped AND attnum > 0
          AND ((attrelid = 'public.cultivo'::regclass
                AND attname IN ('id_agricultor', 'fecha_creacion'))
            OR (attrelid = 'public.agricultor'::regclass
                AND attname = 'id_cultivo_seleccionado'))
    ) THEN
        RAISE EXCEPTION 'Se detectaron columnas de Etapa 2; revisar el estado de la base. No volver a ejecutar esta migración';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.cultivo'::regclass
          AND conname = 'fk_cultivo_parcela' AND contype = 'f'
          AND confrelid = 'public.parcela'::regclass
    ) THEN
        RAISE EXCEPTION 'No se encontró la FK anterior fk_cultivo_parcela';
    END IF;

    IF to_regprocedure('public.sp_registrar_cultivo(uuid,character varying,character varying,date,date,character varying,text)') IS NULL THEN
        RAISE EXCEPTION 'No se encontró la firma anterior de sp_registrar_cultivo';
    END IF;
    IF to_regprocedure('public.sp_seleccionar_cultivo(uuid,uuid)') IS NOT NULL
       OR to_regprocedure('public.sp_obtener_contexto_seleccionado(uuid)') IS NOT NULL THEN
        RAISE EXCEPTION 'Ya existen rutinas nuevas de Etapa 2; revisar antes de migrar';
    END IF;

    FOREACH v_firma IN ARRAY ARRAY[
        'public.sp_listar_cultivos_agricultor(uuid)',
        'public.sp_obtener_contexto_cultivo(uuid,uuid)'
    ] LOOP
        v_oid := to_regprocedure(v_firma);
        IF v_oid IS NULL THEN
            RAISE EXCEPTION 'No se encontró la función %', v_firma;
        END IF;

        SELECT p.*, r.rolname AS propietario INTO v_funcion
        FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
        WHERE p.oid = v_oid;
        -- DROP/CREATE no conserva permisos, propietario ni atributos propios.
        -- Se aborta si difieren de los del script original, sin perderlos.
        IF v_funcion.prokind <> 'f'
           OR v_funcion.propietario <> current_user
           OR v_funcion.proacl IS NOT NULL
           OR v_funcion.proconfig IS NOT NULL
           OR v_funcion.prosecdef
           OR v_funcion.provolatile <> 'v'
           OR v_funcion.proisstrict
           OR v_funcion.proleakproof
           OR v_funcion.proparallel <> 'u'
           OR v_funcion.procost <> 100
           OR v_funcion.prorows <> 1000
           OR obj_description(v_oid, 'pg_proc') IS NOT NULL THEN
            RAISE EXCEPTION 'La función % tiene propietario, permisos o atributos personalizados; preparar su preservación antes de migrar', v_firma;
        END IF;

        SELECT string_agg(pg_describe_object(d.classid, d.objid, d.objsubid), E'\n')
        INTO v_dependencias
        FROM pg_depend d
        WHERE d.refclassid = 'pg_proc'::regclass AND d.refobjid = v_oid;
        IF v_dependencias IS NOT NULL THEN
            RAISE EXCEPTION 'La función % tiene dependencias; no se reemplazará', v_firma
                USING DETAIL = v_dependencias;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_depend d
            WHERE d.classid = 'pg_proc'::regclass AND d.objid = v_oid
              AND d.deptype IN ('e', 'x')
        ) THEN
            RAISE EXCEPTION 'La función % está vinculada a una extensión; revisar manualmente', v_firma;
        END IF;
    END LOOP;
END;
$preflight$;

-- 1-4. Incorporar el propietario sin descartar cultivos existentes.
ALTER TABLE public.cultivo ADD COLUMN id_agricultor UUID;

UPDATE public.cultivo c
SET id_agricultor = p.id_agricultor
FROM public.parcela p
WHERE p.id_parcela = c.id_parcela;

DO $validar_propietarios$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.cultivo c
        LEFT JOIN public.agricultor a ON a.id_agricultor = c.id_agricultor
        WHERE c.id_agricultor IS NULL OR a.id_agricultor IS NULL
    ) THEN
        RAISE EXCEPTION 'Hay cultivos sin propietario válido; se revierte toda la migración';
    END IF;
END;
$validar_propietarios$;

ALTER TABLE public.cultivo ALTER COLUMN id_agricultor SET NOT NULL;

-- 5. El esquema anterior no almacenaba la creación del cultivo.
-- Para filas existentes CURRENT_TIMESTAMP representa la incorporación durante
-- esta migración (inicio de esta transacción), NO una fecha histórica recuperada.
-- No se deduce a partir de fecha_siembra ni de registros de mediciones.
ALTER TABLE public.cultivo
    ADD COLUMN fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
COMMENT ON COLUMN public.cultivo.fecha_creacion IS
    'Creación del cultivo. Para filas anteriores a Etapa 2: fecha de incorporación durante la migración, no fecha histórica conocida.';

-- 6. Instalar y validar primero la nueva relación, luego retirar la FK simple.
ALTER TABLE public.parcela ADD CONSTRAINT uq_parcela_propietario
    UNIQUE (id_parcela, id_agricultor);
ALTER TABLE public.cultivo ADD CONSTRAINT uq_cultivo_propietario
    UNIQUE (id_cultivo, id_agricultor);
ALTER TABLE public.cultivo ADD CONSTRAINT fk_cultivo_parcela_propietario
    FOREIGN KEY (id_parcela, id_agricultor)
    REFERENCES public.parcela(id_parcela, id_agricultor)
    ON UPDATE RESTRICT ON DELETE CASCADE;
ALTER TABLE public.cultivo DROP CONSTRAINT fk_cultivo_parcela RESTRICT;

-- 7-8. No seleccionar automáticamente ningún cultivo, incluso para agricultores
-- ya existentes. La FK verifica propietario y existencia con una sola referencia.
ALTER TABLE public.agricultor
    ADD COLUMN id_cultivo_seleccionado UUID NULL DEFAULT NULL;
ALTER TABLE public.agricultor ADD CONSTRAINT fk_agricultor_cultivo_seleccionado
    FOREIGN KEY (id_cultivo_seleccionado, id_agricultor)
    REFERENCES public.cultivo(id_cultivo, id_agricultor)
    ON UPDATE RESTRICT
    ON DELETE SET NULL (id_cultivo_seleccionado);

-- 9. Índice transaccional; no utilizar CONCURRENTLY dentro de BEGIN/COMMIT.
CREATE INDEX idx_cultivo_agricultor_fecha
    ON public.cultivo(id_agricultor, fecha_creacion DESC, id_cultivo);

-- 10. RESTRICT vuelve a verificar dependencias al ejecutar los DROP.
-- No cambian las firmas de entrada, pero sí las columnas de RETURNS TABLE.
DROP FUNCTION public.sp_listar_cultivos_agricultor(UUID) RESTRICT;
DROP FUNCTION public.sp_obtener_contexto_cultivo(UUID, UUID) RESTRICT;

-- Definiciones actuales copiadas de procedures_postgresql.sql.

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


COMMIT;
