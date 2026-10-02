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
