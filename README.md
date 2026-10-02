# Logística internacional con monitoreo IoT — Persistencia Políglota

Trabajo Práctico de Ingeniería de Datos II (UADE). Aplicación de consola en Python sobre PostgreSQL,
MongoDB, Neo4j y Redis.

> Borrador: este README se completa en la fase de documentación.

## Requisitos

- Python 3.11
- Docker con Docker Compose

## Puesta en marcha

Windows (PowerShell):

```powershell
Copy-Item .env.example .env        # completar las claves
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d
```

Linux:

```bash
cp .env.example .env               # completar las claves
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d
```

## Datos de prueba y usuarios

```
python -m app.datos_prueba
```

| Rol | Email | Contraseña |
|---|---|---|
| ADMIN | admin@logistica.com | admin1234 |
| OPERADOR | operador@logistica.com | operador123 |
| CLIENTE (Frigorífico Pampa) | compras@frigorificopampa.com.ar | cliente123 |

## Inicializar las bases

```
python -m app.inicializar
```

Espera a que los contenedores estén saludables, ejecuta los scripts de `scripts/` e inicia el replica set
de MongoDB si hace falta. Se puede ejecutar más de una vez.

Cada script también se puede ejecutar por separado (los valores son los de `.env.example`):

```
docker compose exec postgres psql -U logistica -d logistica -v ON_ERROR_STOP=1 -f /scripts/postgres.sql
docker compose exec mongo mongosh --quiet --port 27018 --eval "rs.initiate({_id: 'rs0', members: [{_id: 0, host: 'localhost:27018'}]})"
docker compose exec mongo mongosh --quiet --port 27018 logistica --file /scripts/mongo_init.js
docker compose exec neo4j cypher-shell -u neo4j -p <NEO4J_PASSWORD> -f /scripts/neo4j.cypher
```
