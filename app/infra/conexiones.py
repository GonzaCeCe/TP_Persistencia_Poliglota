import psycopg
import redis
from neo4j import Driver, GraphDatabase
from psycopg.rows import dict_row
from pymongo import MongoClient
from pymongo.database import Database

from app.config import Config

TIMEOUT_SEGUNDOS = 5
REINTENTOS_NEO4J_SEGUNDOS = 0


class Conexiones:
    def __init__(self, config: Config):
        self._config = config
        self._pg: psycopg.Connection | None = None
        self._mongo = MongoClient(
            host=config.mongo_host,
            port=config.mongo_port,
            replicaSet=config.mongo_replica_set,
            tz_aware=True,
            w="majority",
            readConcernLevel="majority",
            serverSelectionTimeoutMS=TIMEOUT_SEGUNDOS * 1000,
        )
        self._neo4j = GraphDatabase.driver(
            f"bolt://{config.neo4j_host}:{config.neo4j_bolt_port}",
            auth=(config.neo4j_user, config.neo4j_password),
            connection_timeout=TIMEOUT_SEGUNDOS,
            max_transaction_retry_time=REINTENTOS_NEO4J_SEGUNDOS,
        )
        self._redis = redis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            decode_responses=True,
            socket_connect_timeout=TIMEOUT_SEGUNDOS,
        )

    def postgres(self) -> psycopg.Connection:
        if self._pg is None or self._pg.closed or self._pg.broken:
            self._pg = psycopg.connect(
                host=self._config.pg_host,
                port=self._config.pg_port,
                dbname=self._config.pg_db,
                user=self._config.pg_user,
                password=self._config.pg_password,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=TIMEOUT_SEGUNDOS,
            )
        return self._pg

    def mongo(self) -> Database:
        return self._mongo[self._config.mongo_db]

    def neo4j(self) -> Driver:
        return self._neo4j

    def redis(self) -> redis.Redis:
        return self._redis

    def cerrar(self) -> None:
        if self._pg is not None:
            self._pg.close()
        self._mongo.close()
        self._neo4j.close()
        self._redis.close()
