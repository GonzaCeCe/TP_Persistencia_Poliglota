import argparse
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.ensamblado import crear_aplicacion
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import NIVEL_ADMIN, SesionActiva


log = logging.getLogger(__name__)
HORA_EJECUCION_UTC = 9
INTERVALO_SEGUNDOS = 60


def periodo_anterior(hoy):
    return (hoy.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def sesion_automatica():
    return SesionActiva(
        id="proceso-automatico",
        usuario_id=0,
        nombre="Sistema",
        nivel=NIVEL_ADMIN,
        roles=("ADMIN",),
        cliente_id=None,
    )


def ejecutar_proceso(app, modo, hoy):
    identificador = hoy.isoformat() if modo == "diario" else periodo_anterior(hoy)
    redis = app.conexiones.redis()
    completado = f"tp:procesos:{modo}:{identificador}:completado"
    bloqueo = f"tp:procesos:{modo}:{identificador}:bloqueo"

    if redis.exists(completado):
        return

    token = str(uuid4())

    if not redis.set(bloqueo, token, nx=True, ex=3600):
        return

    try:
        if redis.exists(completado):
            return

        sesion = sesion_automatica()

        if modo == "diario":
            inactivos = app.monitoreo.detectar_sensores_inactivos(sesion)
            predicciones = app.prediccion.predecir_riesgos(sesion, dia=hoy)
            print(
                f"{identificador}: {len(inactivos)} sensores inactivos, "
                f"{len(predicciones)} predicciones"
            )
        else:
            periodo = identificador
            repositorio = RepositorioRelacional(app.conexiones)

            if repositorio.existe_cierre(periodo):
                print(f"{periodo}: cierre mensual ya realizado")
            else:
                facturas = app.comercial.facturar_periodo(sesion, periodo)
                cierres = app.comercial.cierre_mensual(sesion, periodo)
                print(
                    f"{periodo}: {len(facturas['facturas'])} facturas, "
                    f"{cierres} cuentas cerradas"
                )

        redis.set(completado, datetime.now(timezone.utc).isoformat())
        print(f"Proceso {modo} completado")

    finally:
        redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            bloqueo,
            token,
        )


def ejecutar_una_vez(modo, hoy):
    app = crear_aplicacion()

    try:
        ejecutar_proceso(app, modo, hoy)
    finally:
        app.cerrar()


def ejecutar_servicio():
    print("Programador automático iniciado. Ctrl+C para detener.", flush=True)

    while True:
        ahora = datetime.now(timezone.utc)

        if ahora.hour >= HORA_EJECUCION_UTC:
            for modo in ("diario", "mensual"):
                try:
                    ejecutar_una_vez(modo, ahora.date())
                except Exception:
                    log.exception("Falló el proceso %s", modo)

        time.sleep(INTERVALO_SEGUNDOS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--modo",
        choices=("diario", "mensual", "servicio"),
        required=True,
    )
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()

    hoy = datetime.now(timezone.utc).date()

    if args.simular:
        if args.modo == "servicio":
            print("Simulación: diario desde las 09:00 UTC y mensual desde el día 1")
        elif args.modo == "diario":
            print(f"Simulación del proceso diario: {hoy}")
        else:
            print(f"Simulación del proceso mensual: {periodo_anterior(hoy)}")
        return

    if args.modo == "servicio":
        try:
            ejecutar_servicio()
        except KeyboardInterrupt:
            print("Programador detenido")
    else:
        ejecutar_una_vez(args.modo, hoy)


if __name__ == "__main__":
    main()