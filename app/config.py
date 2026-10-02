import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


class ConfiguracionFaltante(Exception):
    pass


def _leer(nombre: str) -> str:
    valor = os.getenv(nombre)
    if valor is None or valor.strip() == "":
        raise ConfiguracionFaltante(f"Falta la variable {nombre} en .env (ver .env.example)")
    return valor.strip()


@dataclass(frozen=True)
class Config:
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    mongo_host: str
    mongo_port: int
    mongo_db: str
    mongo_replica_set: str
    neo4j_host: str
    neo4j_bolt_port: int
    neo4j_user: str
    neo4j_password: str
    redis_host: str
    redis_port: int
    margen_facturacion: Decimal
    sesion_ttl_segundos: int
    heartbeat_ttl_segundos: int
    umbral_bateria: float
    minutos_gracia_sensor: int
    log_archivo: Path


def cargar_config() -> Config:
    load_dotenv(RAIZ / ".env")
    return Config(
        pg_host=_leer("PG_HOST"),
        pg_port=int(_leer("PG_PORT")),
        pg_db=_leer("PG_DB"),
        pg_user=_leer("PG_USER"),
        pg_password=_leer("PG_PASSWORD"),
        mongo_host=_leer("MONGO_HOST"),
        mongo_port=int(_leer("MONGO_PORT")),
        mongo_db=_leer("MONGO_DB"),
        mongo_replica_set=_leer("MONGO_REPLICA_SET"),
        neo4j_host=_leer("NEO4J_HOST"),
        neo4j_bolt_port=int(_leer("NEO4J_BOLT_PORT")),
        neo4j_user=_leer("NEO4J_USER"),
        neo4j_password=_leer("NEO4J_PASSWORD"),
        redis_host=_leer("REDIS_HOST"),
        redis_port=int(_leer("REDIS_PORT")),
        margen_facturacion=Decimal(_leer("MARGEN_FACTURACION")),
        sesion_ttl_segundos=int(_leer("SESION_TTL_SEGUNDOS")),
        heartbeat_ttl_segundos=int(_leer("HEARTBEAT_TTL_SEGUNDOS")),
        umbral_bateria=float(_leer("UMBRAL_BATERIA")),
        minutos_gracia_sensor=int(_leer("MINUTOS_GRACIA_SENSOR")),
        log_archivo=RAIZ / _leer("LOG_ARCHIVO"),
    )
