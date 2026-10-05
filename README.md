# Logística internacional con monitoreo IoT — Persistencia Políglota

Trabajo Práctico de Ingeniería de Datos II (UADE). Aplicación de consola en Python sobre **PostgreSQL 16**,
**MongoDB 7**, **Neo4j 5** y **Redis 7**.

- Informe técnico (arquitectura, justificación, modelos físicos, CAP, consistencia): [`docs/informe_tecnico.md`](docs/informe_tecnico.md)
- Decisiones y supuestos: [`docs/decisiones.md`](docs/decisiones.md)
- Guía de agregaciones de MongoDB, con su equivalente SQL (estudio para la defensa): [`docs/guia_agregaciones.md`](docs/guia_agregaciones.md)
- Enunciado: [`docs/TP_Persistencia_Poliglota.pdf`](docs/TP_Persistencia_Poliglota.pdf)

## Requisitos

- Python **3.11** (no 3.12 o superior)
- Docker con Docker Compose
- Puertos libres en `127.0.0.1`: 5432 (PostgreSQL), 27018 (MongoDB), 7474 y 7687 (Neo4j), 6379 (Redis). Se
  cambian en `.env`.

## Instalación

Windows (PowerShell):

```powershell
Copy-Item .env.example .env        # completar PG_PASSWORD y NEO4J_PASSWORD (mínimo 8 caracteres)
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux:

```bash
cp .env.example .env               # completar PG_PASSWORD y NEO4J_PASSWORD (mínimo 8 caracteres)
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Puesta en marcha

Con el entorno virtual activado, los mismos comandos sirven en los dos sistemas:

```
docker compose up -d               # levanta las 4 bases
python -m app.inicializar          # crea los esquemas e inicia el replica set de MongoDB
python -m app.datos_prueba         # carga los datos de prueba usando los servicios
python -m app.main                 # aplicación de consola
```

`app.inicializar` espera a que los contenedores estén saludables, ejecuta los scripts de `scripts/` e inicia
el replica set `rs0` si hace falta. Se puede ejecutar más de una vez.

Cada script también se puede ejecutar por separado (valores de `.env.example`):

```
docker compose exec postgres psql -U logistica -d logistica -v ON_ERROR_STOP=1 -f /scripts/postgres.sql
docker compose exec mongo mongosh --quiet --port 27018 --eval "rs.initiate({_id: 'rs0', members: [{_id: 0, host: 'localhost:27018'}]})"
docker compose exec mongo mongosh --quiet --port 27018 logistica --file /scripts/mongo_init.js
docker compose exec neo4j cypher-shell -u neo4j -p <NEO4J_PASSWORD> -f /scripts/neo4j.cypher
```

Para volver a cargar los datos de prueba desde cero (`datos_prueba` se niega a correr si ya hay datos):

```
docker compose down -v
docker compose up -d
python -m app.inicializar
python -m app.datos_prueba
```

Con las bases vacías y sin datos de prueba, `python -m app.main` pide crear el administrador inicial.

## Usuarios de prueba

| Rol | Email | Contraseña | Ve |
|---|---|---|---|
| ADMIN | admin@logistica.com | admin1234 | Todo, incluidos los procesos periódicos |
| OPERADOR | operador@logistica.com | operador123 | Operación, monitoreo, trazabilidad, pagos, consultas |
| CLIENTE (Frigorífico Pampa SA) | compras@frigorificopampa.com.ar | cliente123 | Solo sus envíos, su cuenta corriente y sus reportes |

El escenario de prueba:
- **Envío 1:** entregado a tiempo.
- **Envío 2:** entregado tarde, con un incidente cerrado.
- **Envío 3:** en tránsito y vencido, con una lectura de 9,8 °C que generó una alerta y un incidente
  automático.
- **Sensor 3:** nunca reportó y quedó INACTIVO.
- **Comercial:** dos facturas (una con pago parcial y otra pagada) y cierres mensuales de enero a agosto
  de 2026.

## Simulador IoT

En otra terminal, con el entorno virtual activado:

```
python -m app.simulador_iot --sensores 1,2 --intervalo 5
```

Envía una lectura por sensor cada 5 segundos hasta Ctrl+C. Las opciones (`--help` las muestra todas) son:
- `--rondas N`: corta después de N rondas.
- `--temperatura`: temperatura base.
- `--prob-anomalia`: probabilidad de un pico de temperatura.
- `--lat` y `--lon`: posición inicial.
- `--semilla`: repite una simulación.

Para ver las alertas en vivo, entrá como OPERADOR o ADMIN en *Comunicación > Monitor de alertas en tiempo
real*.

El heartbeat de un sensor dura 15 minutos. Si pasa más tiempo sin lecturas, *Procesos periódicos >
Detección de sensores inactivos* lo marca INACTIVO. Vuelve a ACTIVO solo con la próxima lectura (por
ejemplo, del simulador).

## Tests

```
pytest                             # unitarios + integración (requiere las bases y los datos de prueba)
pytest -m "not integracion"        # solo unitarios de dominio, sin bases
```

Los tests de integración dejan los datos como estaban, así que se pueden repetir.

## Salidas

- `logistica.log`: log rotativo de la aplicación (nivel INFO).
- `salidas/`: reportes exportados (JSON o CSV) y recorridos GeoJSON de contenedores. Los `.geojson` se ven
  arrastrándolos a <https://geojson.io>.

## Estructura

```
docker-compose.yml  requirements.txt  .env.example  pytest.ini
scripts/            postgres.sql  mongo_init.js  neo4j.cypher
app/
  main.py           menú de consola (capa ui)
  ensamblado.py     inyección de dependencias
  config.py  inicializar.py  datos_prueba.py  simulador_iot.py
  infra/            conexiones, logs, errores
  dominio/          reglas.py (reglas puras, sin drivers)
  repositorios/     relacional, documental, grafo, clave_valor
  servicios/        auth, operativa, monitoreo, trazabilidad, mensajeria, comercial, reportes, prediccion, sincronizacion
tests/              test_reglas.py (unitarios), test_integracion.py
docs/               informe_tecnico.md, decisiones.md, enunciado
```
