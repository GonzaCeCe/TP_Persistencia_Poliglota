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
