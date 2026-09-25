# Etapa 3A: incorporación e indexación inicial

Esta etapa no migra consultas, respuestas ni fuente_utilizada. No ejecuta ingesta
ni indexación al iniciar la aplicación. Los archivos prueba-*.md no se descubren
automáticamente. El repositorio documental legacy permanece disponible.

## Contrato HTTP

POST /api/v1/knowledge/ingest requiere el nuevo campo `fuente`, texto explícito
no vacío de hasta 150 caracteres, además de `title`, `topic`, `content`.
Sin fuente responde 422; fuente solo con espacios responde 400. No hay fuente
global predeterminada. El cliente que todavía no envíe este campo debe adaptarse
en una etapa posterior: no se ha modificado React.

```json
{
  "title": "Riego de papa — prueba controlada",
  "topic": "papa",
  "content": "Texto aprobado para esta prueba explícita.",
  "fuente": "Material de prueba local"
}
```

Se conservan respuestas de ingest (201), documents (200) e index (200).
`id` es el UUID documental generado por PostgreSQL, `source_path` pasa a ser
`knowledge/<sha256>.md`. El resto de las claves permanece igual. Ingest y listado
conservan `status=registered`; index devuelve `indexed` solo después de confirmar
todos los vínculos del documento. `chunk_count` del adaptador nuevo se calcula
contando fragmentos con vector_id no nulo, no leyendo un contador JSON.

Se mantiene la autenticación existente del controlador de conocimiento, incluido
su Header manual. Para la prueba usar un cliente que envíe realmente
`Authorization: Bearer <JWT>`; no depender del campo manual de Swagger.

## Persistencia y rutinas

PostgreSQL es el catálogo. `sp_registrar_documento` recibe título, tipo `Markdown`,
fuente explícita, autor NULL, fecha de publicación NULL, URL NULL y ruta. Genera
el UUID y fecha de ingreso reales. El documento se registra ACTIVO conforme a la
rutina existente: incorporar un documento es una acción explícita sobre material
aprobado, no un mecanismo automático de revisión editorial.

El DDL no contiene hash ni topic. Sin cambiarlo, el hash se conserva en el nombre
del archivo referenciado por documento.ruta_archivo; topic queda en el .meta.json
adyacente. El Markdown conserva exactamente los bytes UTF-8 recibidos después
del recorte de extremos de la ingesta. No se normalizan saltos al escribir/leer.
Debe respaldarse knowledge/ junto con PostgreSQL y Chroma. Un JSON ausente o una
ruta incompatible generan un error explícito, no metadatos inventados.

Listar utiliza sp_listar_documentos_activos. El adaptador hace SELECT directo
solo para necesidades no cubiertas por rutinas: duplicados por ruta, fecha de
ingreso, fragmentos pendientes, conteos y detección de conflictos. No usa la tabla
documentos_conocimiento. Los errores SQL inesperados no se traducen a duplicados.

## Indexación y recuperación

1. Adquirir un advisory lock de sesión en una conexión dedicada AUTOCOMMIT.
2. Listar exclusivamente el catálogo activo; leer y verificar hash del contenido.
3. Aplicar el fragmentador existente, sin alterar su algoritmo.
4. En una transacción corta, comparar los fragmentos existentes y crear los que
   falten mediante sp_registrar_fragmento, con vector_id=NULL. Reutilizar sus UUID.
5. Cerrar esa transacción y calcular embeddings mediante el puerto existente.
6. Upsert de los IDs `<hash>:chunk:0000` en Chroma. Metadata conserva sus claves y
   añade fragment_id UUID; document_id contiene ahora el UUID documental real.
7. Solo cuando upsert retorna correctamente, confirmar todos los vector_id de ese
   documento en una transacción corta con sp_actualizar_vector_fragmento.
8. Liberar el lock aun si falla una operación. Si falla su liberación se invalida
   la conexión para que un lock no vuelva al pool.

El bloqueo de incorporación usa la misma clave mediante un advisory lock de
transacción. Cuando el catálogo está ocupado, se rechaza la operación para que el
cliente reintente; no se espera indefinidamente. No hay una transacción SQL abierta
durante embeddings o llamadas a Chroma, aunque sí una conexión dedicada al lock.

| Fallo | Resultado y recuperación |
|---|---|
| Registro documental falla | SQL revierte; pueden quedar archivos huérfanos. El reintento consulta SQL primero y reutiliza archivos compatibles. No se borran archivos ante un commit incierto. |
| Preparación de fragmentos falla | Se revierte todo ese lote SQL. No se llama a Chroma. |
| Embedding o Chroma falla, incluso tras escribir parte del lote | No se confirman nuevos vínculos; los fragmentos quedan pendientes. Se propaga el error. |
| Chroma termina y falla la confirmación SQL | Los vectores pueden existir sin vínculo confirmado. Repetir index completa la confirmación usando exactamente los mismos IDs. |
| Repetición completa | Se reutilizan UUID, se repite upsert con IDs iguales y se confirman vínculos; no se agregan filas por el flujo cooperante. |
| Catálogo parcialmente poblado | Se reutilizan los fragmentos compatibles y se crean únicamente los faltantes. |
| Contenido, fragmentos o IDs contradictorios | Se aborta; no se eliminan sobrantes ni se sobrescriben vectores con otra fragmentación. |

Un error interrumpe la petición; documentos anteriores ya completados no se
revierten. La unidad de confirmación es un documento, no todo el catálogo.
Un fallo de infraestructura se propaga como error, nunca como éxito `indexed`.

## Resolución y límites

resolver_vectores llama sp_obtener_fragmentos_por_vector_ids(TEXT[]) y transforma
solo los UUID relacionales a str. Nunca transforma vector_id a UUID. Rechaza más
de una fila por vector_id. La rutina solo devuelve documentos ACTIVO; un ID no
resuelto no produce un UUID ficticio. Esta capacidad aún no está conectada a RAG.

No existe transacción distribuida PostgreSQL/Chroma ni outbox en el DDL. El lock
coordina este adaptador, no scripts externos, una caída de conexión que pierda el
lock ni otros escritores que no lo respeten. No hay UNIQUE de vector_id/ruta ni
de documento+orden en la base: la idempotencia es del flujo cooperante. El esquema
no registra la colección ni la versión del modelo de embeddings. Mantener colección,
modelo, dimensión y configuración estables durante recuperación. Un cambio de
configuración necesita un diseño posterior; este flujo no elimina vectores viejos.

No se comprueba con una lectura posterior cada vector después del upsert: la
confirmación confía en el éxito devuelto por el adaptador Chroma. Una eliminación
externa posterior tampoco queda detectada por chunk_count. Reindexar permite
restablecer los registros con los mismos IDs.

El RAG actual consulta Chroma directamente y podría ver un vector aún no
confirmado en PostgreSQL. Resolver exclusivamente evidencias relacionales
confirmadas será responsabilidad de Etapa 3B. No se ha implementado
fuente_utilizada ni modificado /api/v1/queries.

## Prueba real controlada posterior (no ejecutada en esta entrega)

1. Confirmar la base, knowledge_dir y colección efectivos y tener respaldos.
   Mantener detenida cualquier otra ingesta/indexación. Revisar GET
   /api/v1/knowledge/documents: index procesa TODOS los documentos activos.
2. Arrancar el backend desde backend/ con la configuración prevista. Obtener un
   JWT con el login existente. No crear ni recrear la colección.
3. En un cliente HTTP enviar el JSON anterior a POST
   http://127.0.0.1:8000/api/v1/knowledge/ingest con Content-Type: application/json
   y Authorization: Bearer <JWT>. Usar material explícitamente aprobado para
   pruebas; no atribuirlo a una institución oficial.
4. Comprobar 201, UUID documental y chunk_count=0. Guardar el UUID devuelto.
   Con SELECT comprobar documento.id_documento, fuente, ruta_archivo y que no
   se han inventado autor, publicación o URL.
5. Enviar POST http://127.0.0.1:8000/api/v1/knowledge/index con el mismo header.
   Comprobar 200, total_chunks y estado indexed. No continuar con queries.
6. Mediante SELECT revisar fragmento para ese UUID: id_fragmento UUID, orden desde
   cero y vector_id=<content_hash>:chunk:<orden con mínimo cuatro dígitos>.
7. Leer IDs/textos/metadata de la colección existente sin get_or_create_collection.
   Comparar cada vector con sp_obtener_fragmentos_por_vector_ids: exactamente una
   fila, mismo texto, mismo id_documento y mismo id_fragmento que la metadata.
8. Repetir index. Verificar que los UUID, los conteos relacionales y el conjunto
   de IDs en Chroma permanecen iguales. No inducir fallos en servicios reales:
   los fallos parciales se prueban con dobles.
9. Repetir ingest del mismo contenido: debe responder 409, sin duplicados. No
   borrar el material automáticamente; registrar que es de prueba y decidir su
   tratamiento antes de habilitar consultas para usuarios.

## Pruebas aisladas

Desde backend/, primero ejecutar pytest sobre test_ingest_knowledge.py,
test_chunking.py, test_index_knowledge.py, test_knowledge_endpoint.py y
test_knowledge_postgresql_unit.py. Luego ejecutar test_architecture.py,
test_auth_postgresql_unit.py, test_register_farmer.py, test_login_farmer.py,
test_context_postgresql_unit.py y test_agricultural_context.py.

No ejecutar indiscriminadamente toda la suite: quedan pruebas de integración
legacy que importan app.main y pueden tocar servicios reales. Las pruebas de
Etapa 3A utilizan dobles y directorios temporales; no validan la ejecución real
de las rutinas instaladas, que queda para la prueba controlada anterior.
