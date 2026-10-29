# Decisiones y supuestos

Registro de las decisiones tomadas donde el enunciado es ambiguo o no dice nada. Cada una indica qué se
decidió y por qué.

## D1. Lista de motores obligatorios incompleta en el enunciado

El enunciado (página 8, "Restricciones técnicas → Persistencia") dice "La solución deberá utilizar
obligatoriamente:" pero la lista está vacía en el PDF entregado. Se toma como requisito el mínimo explícito
de la sección 1: al menos tres paradigmas. Se usan cuatro: relacional (PostgreSQL), documental (MongoDB),
grafos (Neo4j) y clave-valor (Redis).

**Riesgo:** si la cátedra exigía un motor puntual (por ejemplo Cassandra), habría que agregarlo. La
justificación de por qué se descartaron Cassandra y la base de objetos está en el informe técnico.

## D2. Límite de "máximo 3 registros por entidad" en los datos de prueba

El límite aplica a las entidades que se cargan explícitamente (clientes, empresas, usuarios, contenedores,
sensores, vehículos, envíos, incidentes, pagos, mensajes, grupos). Para eventos y lecturas el límite es de
3 por envío y 3 por sensor respectivamente, porque el escenario pide envíos entregados (que necesitan al
menos inicio, tránsito y entrega) y un recorrido GPS reconstruible. Los registros que generan los procesos
(ítems de factura, movimientos de cuenta corriente, cierres mensuales, alertas, predicciones, reportes) no
tienen límite: su cantidad la determina la regla de negocio, no la carga.

## D3. Alcance agregado al menú

Para cubrir requisitos que el enunciado nombra pero que no tenían opción propia:

- **Alta de vehículo:** los tramos referencian vehículos y los datos de prueba se cargan usando servicios.
- **Listar y consultar** clientes, empresas y contenedores: completa la "R" del CRUD pedido.
- **Cambio de estado de contenedor** (MANTENIMIENTO / BAJA / DISPONIBLE) **y de sensor**: cubre "Gestión de
  contenedores". El estado EN_USO no se asigna a mano: lo maneja la reserva al registrar un envío.

## D4. Roles fijos

"Administración de usuarios y roles" se resuelve con roles fijos (ADMIN = 5, OPERADOR = 3, CLIENTE = 1),
cargados por el script de creación, y con la asignación de roles a usuarios. No hay CRUD de roles: los
niveles de permiso los interpreta el código del menú, así que crear roles nuevos no tendría efecto.

## D5. Operador del tramo

El operador de un tramo se toma de la empresa del vehículo elegido, que debe ser de tipo OPERADOR y estar
ACTIVO. Así se evita cargar un operador inconsistente con el vehículo.

## D6. Compatibilidad entre medio de transporte y vehículo

TERRESTRE ↔ CAMION o TREN · MARITIMO ↔ BUQUE · AEREO ↔ AVION.

## D7. Fechas de los hechos registrados

Los servicios que registran hechos con fecha (envío, tramo, evento, lectura, pago, incidente) aceptan una
fecha opcional; si no se indica se usa la fecha actual. Así los datos de prueba pueden ubicarse entre
2026-01-01 y 2026-09-30 sin insertar directamente en las bases, y el operador puede registrar un hecho
ocurrido antes de cargarlo.

## D8. Entorno local de las bases

- Puertos publicados solo en `127.0.0.1`.
- MongoDB y Redis sin autenticación: es un entorno local de desarrollo; activar autenticación en el replica
  set exige un keyfile compartido, que no aporta al objetivo del TP. PostgreSQL y Neo4j sí usan usuario y
  clave (Neo4j la exige). En producción se habilitaría en todos (ver mejoras propuestas en el informe).
- El Mongo del contenedor escucha en `MONGO_PORT` (27018 por defecto) dentro y fuera del contenedor, y el
  replica set anuncia el miembro `localhost:MONGO_PORT`. Así el driver, que se conecta al host anunciado
  por el replica set, llega al contenedor aunque exista otro MongoDB local en 27017.
- Los datos viven en volúmenes de Docker (no en carpetas montadas), para que la sincronización de
  OneDrive no interfiera con los archivos de las bases.

## D9. Capa de consola

La capa `ui` es `app/main.py`, con una función por submenú, siguiendo la estructura de carpetas fijada.

## D10. `lecturas` como colección común

`lecturas` es una colección común con campos planos (`sensor_id`, `contenedor_id`, `fecha_hora` y las
medidas), validador `$jsonSchema` (obligatorios `sensor_id`, `contenedor_id` y `fecha_hora`; medidas
opcionales con rangos) e índices compuestos `{sensor_id: 1, fecha_hora: -1}` (histórico de un sensor) y
`{contenedor_id: 1, fecha_hora: 1}` (recorrido de un contenedor). El dominio también valida los rangos
antes de insertar.

Al principio era una colección *time series*, que en MongoDB 7 no admite validador. Se reemplazó porque las
time series no se vieron en la materia; así todas las colecciones quedan con `$jsonSchema`.

## D11. Ruta de un incidente

`incidente.ruta` es el par origen-destino **del envío** (por ejemplo `ARBUE-BRSSZ`), no del tramo. El
tramo afectado queda identificado en `incidente.tramo_id`. Se usa la ruta del envío porque es la misma
unidad que usa la predicción ("tasa histórica de demora de la ruta"), así el ranking de rutas con más
incidentes y la predicción hablan de lo mismo. Los códigos de ubicación siguen el formato UN/LOCODE
(2 letras de país + 3 caracteres).

## D12. Ejecución de los scripts de creación

`docker-compose.yml` monta `./scripts` en `/scripts` (solo lectura) dentro de los contenedores de
PostgreSQL, MongoDB y Neo4j. Los scripts se ejecutan con `psql -f`, `mongosh --file` y `cypher-shell -f`
en lugar de pasarlos por stdin: así un error corta la ejecución con código distinto de cero, la salida es
limpia y el mismo comando funciona igual en PowerShell y en bash. Los scripts usan solo caracteres ASCII.

## D13. Usuarios, roles y alcance

- El rol CLIENTE va siempre con `cliente_id`, y un usuario con `cliente_id` solo puede tener ese rol. Así
  la restricción de alcance ("solo ve lo suyo") depende de un único dato de la sesión.
- El primer usuario se crea con "crear administrador inicial", que solo funciona con la base sin usuarios.
  Los datos de prueba lo usan para obtener una sesión de ADMIN y cargar todo a través de los servicios.
- La red de relaciones y el impacto de una ubicación son consultas internas (OPERADOR o más): muestran
  nombres de otros clientes. Un usuario de cliente sí puede ver la ruta completa de sus propios envíos.
- El hash de sesión en Redis guarda, además de usuario, nivel, roles y cliente, el nombre del usuario, que
  usa la consola para saludar sin consultar PostgreSQL en cada pantalla.
- Un cambio de roles se aplica en el próximo login (la sesión activa conserva el nivel con que se creó).

## D14. Envíos y eventos

- Se agrega **cancelar envío**, solo en estado CREADO (antes de la carga): libera los contenedores. Sin esta
  operación el estado CANCELADO del enunciado no tendría forma de alcanzarse.
- El volumen del envío no puede superar la suma de capacidades de sus contenedores.
- El origen de cada tramo debe ser el destino del tramo anterior (o el origen del envío, si es el
  primero), y la salida no puede ser anterior a la creación del envío.
- Un evento solo cambia el estado del envío si es más nuevo que `ultimo_evento`; uno anterior queda en el
  historial sin modificar el estado. No se aceptan eventos posteriores a la entrega ni la entrega de un
  envío sin tramos (no tendría costo para facturar).
- `cantidad_incidentes` cuenta todos los incidentes del envío (abiertos y cerrados): es el dato que usa el
  reporte de promedio de incidentes. Cerrar un incidente no lo decrementa.
- El tiempo de envío se mide desde `fecha_creacion` hasta `fecha_entrega_real`, en días con decimales.
  Todas las fechas se guardan en UTC.

- "Listar envíos" acepta un filtro opcional por país de destino. Es la consulta que usa el índice
  `{destino.pais}`: el reporte "envíos por país" agrupa todos los envíos con `$group` y un agrupamiento
  sin filtro no aprovecha índices.

## D15. Lecturas, alertas y sensores

- `registrar_lectura` no recibe sesión: es la puerta de entrada de los dispositivos (y del simulador). La
  consola exige nivel OPERADOR antes de ofrecer la carga manual.
- Un sensor en BAJA o FALLA rechaza lecturas; uno sin contenedor asociado también.
- La alerta SENSOR_INACTIVO se cierra automáticamente cuando el sensor vuelve a reportar. Las demás se
  cierran manualmente desde el menú.
- Solo la lectura más reciente actualiza `sensor:{id}:ultima` y la posición GEO: una lectura atrasada
  queda en el histórico sin pisar el estado en vivo. El heartbeat sí se renueva con cualquier lectura,
  porque indica que el dispositivo está transmitiendo.

## D16. Facturación, pagos y cierres

- Solo se factura un período terminado, igual que el cierre: así la emisión (primer día del mes siguiente)
  nunca queda en el futuro.
- No se registran movimientos en un período que ya tiene cierre mensual (ni facturas ni pagos): el cierre
  quedaría desactualizado.
- Convención de saldo: saldo = Σ DEBE − Σ HABER. En la cuenta de un cliente, positivo es deuda del
  cliente. En la cuenta de un operador, el HABER por el costo de sus tramos deja el saldo negativo: es lo
  que la empresa le debe al operador.
- El HABER del operador se registra por envío (suma de los costos de sus tramos en ese envío); el índice
  único parcial `(cuenta_id, envio_id)` impide registrarlo dos veces.
- El saldo inicial de un cierre es el saldo final del cierre anterior; si no existe (primer cierre), es
  la suma de los movimientos previos al período.

## D17. Proyección al grafo

- Toda escritura en MongoDB que cambia algo proyectado (envío nuevo, tramo, estado) pone
  `grafo_sincronizado = false` **en la misma operación**. Si la proyección posterior funciona, vuelve a
  `true`. Así, aunque el proceso se corte entre las dos escrituras, el envío queda marcado como pendiente.
- El driver de Neo4j no reintenta las transacciones (`max_transaction_retry_time = 0`): la proyección
  ya tiene su mecanismo de recuperación y reintentar dejaba la consola bloqueada hasta 30 segundos.
- Los hosts se configuran como `127.0.0.1` y no `localhost`: en Windows, `localhost` intenta primero IPv6 y
  cada conexión rechazada suma segundos de espera.

## D18. Comunicación

Un grupo público lo puede leer cualquier usuario; para escribir hay que unirse. Un grupo privado solo lo
leen y escriben sus integrantes.

## D19. Procesos que corren al final de los datos de prueba

La detección de sensores inactivos y la predicción diaria se ejecutan con la fecha real (son procesos "de
hoy"). Por eso esas dos salidas quedan fuera del rango 2026-01-01 a 2026-09-30 que respetan los datos
cargados. Lo mismo ocurre con las sesiones: el login del administrador que hace la carga es real.

## D20. Recarga de los datos de prueba

`python -m app.datos_prueba` se niega a correr si ya hay usuarios y muestra cómo recrear las bases
(`docker compose down -v`, `up -d`, `inicializar`, `datos_prueba`). Se prefirió eso a un borrado desde la
aplicación: no existe ningún camino de código que vacíe las bases, y los IDs vuelven a empezar en 1.

## D21. Reportes con aggregation pipeline básico

Los reportes usan solo `$match`, `$group`, `$sort` y `$unwind` (y `$limit` si hiciera falta), con
`$sum`, `$avg`, `$min`, `$max` y `$first`. No se usan `$dateDiff`, `$dateToString`, `$cond`, `$expr`,
`$project` con cálculos, `$lookup` ni `$facet`.

- Al pasar un envío a ENTREGADO, `reglas.metricas_de_entrega` calcula `dias_entrega`, `demorado` (0/1) y
  `mes_entrega` (`AAAA-MM`), y se guardan en el mismo `updateOne` que cambia el estado. Son opcionales en
  el validador porque solo existen en los entregados.
- Envíos demorados es un `find` con `$or` (en curso y vencido, o `demorado: 1`).
- La tasa de demora de una ruta es `$avg` de `demorado` (el promedio de un 0/1 es una proporción).
- Renombrar `_id`, redondear y calcular porcentajes se hace en Python sobre el resultado ya agrupado.
- "Mis conversaciones" toma el último mensaje con `$sort` + `$first` de cada campo, sin `$$ROOT`.
- No hay índice `{mes_entrega: 1}`: ningún reporte filtra por ese campo.

Cada pipeline, con su equivalente SQL, está en `docs/guia_agregaciones.md`.

## D22. Sin transacciones multi-documento de MongoDB

Se reemplazan por operaciones idempotentes y reconciliación:

- **Registrar evento.** (1) Insert en `eventos`: si el índice único `{envio_id, fecha_hora, tipo}` da clave
  duplicada, es un reintento; se registra en el log y se sigue. (2) `updateOne` condicional del envío
  (solo si el evento es más nuevo que `ultimo_evento`). (3) Si el envío quedó ENTREGADO con este evento
  como último, se liberan los contenedores.
  - La fecha del evento se trunca a milisegundos, la precisión que guarda MongoDB, para poder comparar con
    el `ultimo_evento` guardado.
  - Al liberar, se excluyen los contenedores que ya estén en otro envío activo, porque un reintento tardío
    no debe liberar un contenedor reservado por otro envío.
  - Registrar el mismo evento dos veces no lo duplica: la segunda vez devuelve `duplicado = true` y la
    consola lo informa.
- **Registrar incidente.** Insert y después `$inc`. Si el `$inc` no llega a ejecutarse, el control de
  integridad compara `cantidad_incidentes` con `count_documents` de los incidentes del envío, corrige el
  contador y lo registra en el log.
- **Replica set.** Se mantienen el replica set y `w: majority`: se vieron en clase y siguen justificados
  por la replicación, aunque ya no se usan para transacciones.

## D23. SQL estándar

- `SELECT ... FOR UPDATE` solo en la reserva de contenedores y en el bloqueo de la factura al pagar
  ("bloqueos y granularidad", Clase 1). Se quitó de las cuentas corrientes (`UPDATE saldo = saldo + x` ya
  es atómico) y se quitó el `FOR SHARE` del cliente al registrar un envío. Queda una ventana mínima en la
  que un cliente podría darse de baja mientras se registra su envío; se acepta por simplicidad.
- Sin `ON CONFLICT`:
  - Asignar un rol ya asignado se verifica antes y no hace nada.
  - Cerrar un período ya cerrado devuelve un error de negocio ("El período AAAA-MM ya está cerrado"). Si
    dos cierres corren a la vez, la clave primaria `(cuenta_id, periodo)` rechaza el segundo y se traduce
    al mismo error.
  - Consecuencia: una cuenta creada después de cerrar un mes no recibe el cierre de ese mes. Su próximo
    cierre parte igual del saldo correcto, porque suma sus movimientos previos.
- `FILTER (WHERE ...)` pasa a `SUM(CASE WHEN ... THEN ... ELSE 0 END)`; `CROSS JOIN LATERAL`, a
  subconsultas escalares; `array_agg ... FILTER`, a una segunda consulta simple con los roles del usuario.
- En `scripts/postgres.sql`:
  - la carga de roles usa `INSERT ... SELECT ... WHERE NOT EXISTS` en lugar de `ON CONFLICT`;
  - el titular de la cuenta corriente se valida con `CHECK ((cliente_id IS NULL) <> (empresa_id IS NULL))`
    en lugar de `num_nonnulls`.
- Se mantienen `= ANY(%s)` (forma correcta de pasar listas con psycopg 3), `RETURNING id`,
  `CREATE ... IF NOT EXISTS` y `~` en los `CHECK`.

## D24. Integración del entorno de la otra parte del grupo (`TP_Logistica-main`)

La carpeta traía `compose.yaml`, `requirements.txt`, `.env.example`, `.gitignore` y `test_conexiones.py`. Se
unificó con los archivos del proyecto, en lugar de dejar dos configuraciones en paralelo:
- **Imágenes con versión fija:** `mongo:7.0`, `neo4j:5.26-community` y `redis:7.4`. Coinciden con las
  versiones que ya corrían, así que los volúmenes se reutilizan. Redis queda en 7.4 y no en 7.2: los
  archivos AOF que escribe la 7.4 usan un formato de RDB que la 7.2 no lee, y Redis no arrancaría.
- **Contenedores:** se llaman `tp_postgres`, `tp_mongo`, `tp_neo4j` y `tp_redis`.
- **Librerías:** `pymongo` pasa a 4.19.0 y `neo4j` a 6.4.1. No se agregan `pytz`, `tzdata`, `dnspython` ni
  `typing_extensions`: el código no las usa y pip instala las que hacen falta como dependencias.
- **`.gitignore`:** se suman `.env.*` (salvo `.env.example`) y `.vscode/`.
- **`test_conexiones.py`** pasa a `app/verificar_conexiones.py` (`python -m app.verificar_conexiones`). Usa
  `.env` y las conexiones de la aplicación, así prueba lo mismo que va a usar la app, incluido el replica
  set. Tiene otro nombre para que pytest no lo tome como test.
- **Se mantiene lo del proyecto donde había diferencias:**
  - PostgreSQL 16, del stack definido. La otra carpeta usaba la 17, y los datos de un volumen de la 16 no
    los abre la 17.
  - Usuario `logistica` y variables `PG_*` (la otra carpeta usaba `tp_user` y `POSTGRES_PASSWORD`).
  - El replica set `rs0` y los healthchecks, que usan la aplicación y `app.inicializar`.
