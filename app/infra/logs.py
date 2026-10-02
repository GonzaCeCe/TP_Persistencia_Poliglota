import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
TAMANIO_MAXIMO_BYTES = 1_000_000
ARCHIVOS_DE_RESPALDO = 3


def configurar_logs(archivo: Path) -> None:
    raiz = logging.getLogger()
    if raiz.handlers:
        return
    raiz.setLevel(logging.INFO)

    a_archivo = RotatingFileHandler(archivo, maxBytes=TAMANIO_MAXIMO_BYTES,
                                    backupCount=ARCHIVOS_DE_RESPALDO, encoding="utf-8")
    a_archivo.setLevel(logging.INFO)
    a_archivo.setFormatter(logging.Formatter(FORMATO))

    a_consola = logging.StreamHandler()
    a_consola.setLevel(logging.WARNING)
    a_consola.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    raiz.addHandler(a_archivo)
    raiz.addHandler(a_consola)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.ERROR)
