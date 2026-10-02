import subprocess
import sys
import time

from app.config import RAIZ, Config, ConfiguracionFaltante, cargar_config

SCRIPTS_EN_CONTENEDOR = "/scripts"
SERVICIOS = ("postgres", "mongo", "neo4j", "redis")
ESPERA_MAXIMA_SEGUNDOS = 180


class ErrorInicializacion(Exception):
    pass


def _ejecutar(comando: list[str]) -> str:
    resultado = subprocess.run(comando, capture_output=True, cwd=RAIZ)
    if resultado.returncode != 0:
        detalle = resultado.stderr.decode("utf-8", errors="replace").strip()
        raise ErrorInicializacion(f"{' '.join(comando[:5])} ...: {detalle}")
    return resultado.stdout.decode("utf-8", errors="replace").strip()


def _en_contenedor(servicio: str, comando: list[str]) -> str:
    return _ejecutar(["docker", "compose", "exec", "-T", servicio, *comando])


def esperar_contenedores_saludables() -> None:
    limite = time.monotonic() + ESPERA_MAXIMA_SEGUNDOS
    while time.monotonic() < limite:
        salida = _ejecutar(["docker", "compose", "ps", "--format", "{{.Service}} {{.Health}}"])
        estados = dict(linea.split(maxsplit=1) for linea in salida.splitlines() if " " in linea)
        if all(estados.get(servicio) == "healthy" for servicio in SERVICIOS):
            return
        time.sleep(3)
    raise ErrorInicializacion("Los contenedores no quedaron saludables. ¿Se ejecutó 'docker compose up -d'?")


def inicializar_postgres(config: Config) -> None:
    _en_contenedor("postgres", ["psql", "-U", config.pg_user, "-d", config.pg_db,
                                "-v", "ON_ERROR_STOP=1", "-q", "-f", f"{SCRIPTS_EN_CONTENEDOR}/postgres.sql"])


def _mongosh(config: Config, argumentos: list[str]) -> str:
    return _en_contenedor("mongo", ["mongosh", "--quiet", "--port", str(config.mongo_port), *argumentos])


def iniciar_replica_set(config: Config) -> None:
    miembro = f"localhost:{config.mongo_port}"
    iniciar = (f"try {{ rs.status().ok }} catch (e) {{ "
               f"rs.initiate({{_id: 'rs0', members: [{{_id: 0, host: '{miembro}'}}]}}).ok }}")
    _mongosh(config, ["--eval", iniciar])
    for _ in range(30):
        if _mongosh(config, ["--eval", "db.hello().isWritablePrimary"]) == "true":
            return
        time.sleep(1)
    raise ErrorInicializacion("El replica set de MongoDB no eligió primario")


def inicializar_mongo(config: Config) -> None:
    print("  " + _mongosh(config, [config.mongo_db, "--file", f"{SCRIPTS_EN_CONTENEDOR}/mongo_init.js"]))


def inicializar_neo4j(config: Config) -> None:
    _en_contenedor("neo4j", ["cypher-shell", "-u", config.neo4j_user, "-p", config.neo4j_password,
                             "-f", f"{SCRIPTS_EN_CONTENEDOR}/neo4j.cypher"])


def verificar_redis(config: Config) -> None:
    if _en_contenedor("redis", ["redis-cli", "ping"]) != "PONG":
        raise ErrorInicializacion("Redis no responde")


def main() -> None:
    try:
        config = cargar_config()
        pasos = [
            ("Esperando contenedores", esperar_contenedores_saludables),
            ("PostgreSQL: scripts/postgres.sql", lambda: inicializar_postgres(config)),
            ("MongoDB: replica set rs0", lambda: iniciar_replica_set(config)),
            ("MongoDB: scripts/mongo_init.js", lambda: inicializar_mongo(config)),
            ("Neo4j: scripts/neo4j.cypher", lambda: inicializar_neo4j(config)),
            ("Redis: ping", lambda: verificar_redis(config)),
        ]
        for descripcion, paso in pasos:
            print(f"- {descripcion}")
            paso()
    except (ConfiguracionFaltante, ErrorInicializacion) as error:
        print(f"ERROR: {error}")
        sys.exit(1)
    except FileNotFoundError:
        print("ERROR: no se encontró el comando 'docker'. Instalá Docker y volvé a intentar.")
        sys.exit(1)
    print("Bases inicializadas.")


if __name__ == "__main__":
    main()
