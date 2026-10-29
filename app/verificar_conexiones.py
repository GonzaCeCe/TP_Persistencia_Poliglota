import sys
from typing import Callable

from app.config import ConfiguracionFaltante, cargar_config
from app.infra.conexiones import Conexiones


def _verificaciones(conexiones: Conexiones) -> list[tuple[str, Callable[[], object]]]:
    return [
        ("PostgreSQL", lambda: conexiones.postgres().execute("SELECT 1")),
        ("MongoDB", lambda: conexiones.mongo().command("ping")),
        ("Neo4j", lambda: conexiones.neo4j().verify_connectivity()),
        ("Redis", lambda: conexiones.redis().ping()),
    ]


def main() -> None:
    try:
        conexiones = Conexiones(cargar_config())
    except ConfiguracionFaltante as error:
        print(f"ERROR: {error}")
        sys.exit(1)
    fallas = 0
    try:
        for motor, verificar in _verificaciones(conexiones):
            try:
                verificar()
                print(f"{motor}: conectado correctamente")
            except Exception as error:
                fallas += 1
                print(f"{motor}: ERROR {error}")
    finally:
        conexiones.cerrar()
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    main()
