
import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.ensamblado import Aplicacion, crear_aplicacion
from app.infra.errores import ErrorAplicacion
from app.servicios.auth import SesionActiva

log = logging.getLogger(__name__)

USUARIOS = [
    ("ADMIN", "admin@logistica.com", "admin1234"),
    ("OPERADOR", "operador@logistica.com", "operador123"),
    ("CLIENTE (Frigorífico Pampa)", "compras@frigorificopampa.com.ar", "cliente123"),
]

ROSARIO = {"codigo": "ARROS", "ciudad": "Rosario", "pais": "AR"}
BUENOS_AIRES = {"codigo": "ARBUE", "ciudad": "Buenos Aires", "pais": "AR"}
MENDOZA = {"codigo": "ARMDZ", "ciudad": "Mendoza", "pais": "AR"}
SANTOS = {"codigo": "BRSSZ", "ciudad": "Santos", "pais": "BR"}
NUEVA_YORK = {"codigo": "USNYC", "ciudad": "Nueva York", "pais": "US"}

CORDOBA = {"codigo": "ARCOR", "ciudad": "Córdoba", "pais": "AR"}
LA_PLATA = {"codigo": "ARLPG", "ciudad": "La Plata", "pais": "AR"}
BAHIA_BLANCA = {"codigo": "ARBHI", "ciudad": "Bahía Blanca", "pais": "AR"}
SANTA_FE = {"codigo": "ARSFN", "ciudad": "Santa Fe", "pais": "AR"}
MAR_DEL_PLATA = {"codigo": "ARMDQ", "ciudad": "Mar del Plata", "pais": "AR"}
NEUQUEN = {"codigo": "ARNQN", "ciudad": "Neuquén", "pais": "AR"}
SALTA = {"codigo": "ARSLA", "ciudad": "Salta", "pais": "AR"}
TUCUMAN = {"codigo": "ARTUC", "ciudad": "San Miguel de Tucumán", "pais": "AR"}

CLIENTES_ADICIONALES = [
    ("Distribuidora del Norte SA", "30-90000001-1", "distribuidora.norte@example.com", CORDOBA, BUENOS_AIRES),
    ("Alimentos Patagónicos SRL", "30-90000002-2", "alimentos.patagonicos@example.com", NEUQUEN, BAHIA_BLANCA),
    ("Tecnología Austral SA", "30-90000003-3", "tecnologia.austral@example.com", BUENOS_AIRES, CORDOBA),
    ("Exportadora del Plata SA", "30-90000004-4", "exportadora.plata@example.com", ROSARIO, LA_PLATA),
    ("Industrias Córdoba SRL", "30-90000005-5", "industrias.cordoba@example.com", CORDOBA, SANTA_FE),
    ("Agroexportaciones Pampeanas SA", "30-90000006-6", "agro.pampeanas@example.com", SANTA_FE, ROSARIO),
    ("Textiles del Litoral SRL", "30-90000007-7", "textiles.litoral@example.com", TUCUMAN, SALTA),
    ("Equipamientos Andinos SA", "30-90000008-8", "equipamientos.andinos@example.com", MENDOZA, CORDOBA),
]


def utc(mes: int, dia: int, hora: int = 0) -> datetime:
    return datetime(2026, mes, dia, hora, tzinfo=timezone.utc)


def cargar_maestros(app: Aplicacion, adm: SesionActiva) -> dict:
    op = app.operativa
    ids = {
        "pampa": op.alta_cliente(adm, "Frigorífico Pampa SA", "30-71234567-1", "compras@frigorificopampa.com.ar",
                                 "+54 341 455-0000", "Av. Circunvalación 2500, Rosario", "AR"),
        "andes": op.alta_cliente(adm, "Bodega Los Andes SRL", "30-79876543-2", "export@bodegalosandes.com.ar",
                                 "+54 261 420-1111", "Ruta 40 km 3200, Luján de Cuyo", "AR"),
        "terrestre": op.alta_empresa(adm, "OPERADOR", "Transportes del Sur SA", "30-70000001-1", "AR"),
        "maritimo": op.alta_empresa(adm, "OPERADOR", "Naviera Atlántica SA", "30-70000002-2", "AR"),
        "proveedor": op.alta_empresa(adm, "PROVEEDOR", "Sensores IoT SRL", "30-70000003-3", "AR"),
    }
    ids["camion"] = op.alta_vehiculo(adm, "CAMION", "AE123CD", ids["terrestre"])
    ids["buque"] = op.alta_vehiculo(adm, "BUQUE", "IMO9321483", ids["maritimo"])
    ids["reefer"] = op.alta_contenedor(adm, "MSKU1234565", "REEFER", Decimal("28"), Decimal("2"), Decimal("8"))
    ids["dry"] = op.alta_contenedor(adm, "TGHU7654321", "DRY", Decimal("33"), Decimal("-10"), Decimal("50"))
    ids["sensor_reefer"] = op.alta_sensor(adm, "MULTI", "Bosch", ids["reefer"], utc(1, 5))
    ids["sensor_dry"] = op.alta_sensor(adm, "GPS", "Garmin", ids["dry"], utc(1, 5))
    ids["sensor_mudo"] = op.alta_sensor(adm, "HUMEDAD", "Sensirion", ids["reefer"], utc(1, 5))
    ids["operador"] = app.auth.registrar_usuario(adm, "Oscar", "Operador", USUARIOS[1][1], USUARIOS[1][2],
                                                 ["OPERADOR"], None, utc(1, 3))
    ids["usuario_cliente"] = app.auth.registrar_usuario(adm, "Carla", "Compras", USUARIOS[2][1], USUARIOS[2][2],
                                                        ["CLIENTE"], ids["pampa"], utc(1, 10))
    return ids


def cargar_envio_a_tiempo(app: Aplicacion, adm: SesionActiva, ids: dict) -> int:
    envio = app.operativa.registrar_envio(adm, ids["pampa"], ROSARIO, SANTOS, "ALTA", 18000, 25,
                                          [ids["reefer"]], utc(2, 2, 9))
    app.operativa.agregar_tramo(adm, envio, "TERRESTRE", ROSARIO, BUENOS_AIRES, ids["camion"],
                                utc(2, 3, 6), utc(2, 4, 6), Decimal("800"))
    app.operativa.agregar_tramo(adm, envio, "MARITIMO", BUENOS_AIRES, SANTOS, ids["buque"],
                                utc(2, 5, 6), utc(2, 12, 18), Decimal("3200"))
    app.trazabilidad.registrar_evento(adm, envio, "CARGA_INICIADA", "ARROS - planta frigorífica", "", utc(2, 3, 5))
    app.monitoreo.registrar_lectura(ids["sensor_reefer"], {"temperatura": 4.5, "humedad": 80, "lat": -32.95,
                                                           "lon": -60.64, "bateria": 98}, utc(2, 3, 10))
    app.trazabilidad.registrar_evento(adm, envio, "EN_TRANSITO", "ARBUE - terminal 4", "Zarpó el buque", utc(2, 5, 7))
    app.monitoreo.registrar_lectura(ids["sensor_reefer"], {"temperatura": 5.1, "humedad": 82, "lat": -33.5,
                                                           "lon": -51.0, "bateria": 95}, utc(2, 8, 12))
    app.trazabilidad.registrar_evento(adm, envio, "ENTREGADO", "BRSSZ - terminal Santos", "", utc(2, 11, 15))
    return envio


def cargar_envio_tardio(app: Aplicacion, adm: SesionActiva, ids: dict) -> int:
    envio = app.operativa.registrar_envio(adm, ids["andes"], MENDOZA, NUEVA_YORK, "MEDIA", 21000, 30,
                                          [ids["dry"]], utc(4, 6, 10))
    app.operativa.agregar_tramo(adm, envio, "TERRESTRE", MENDOZA, BUENOS_AIRES, ids["camion"],
                                utc(4, 7, 6), utc(4, 9, 18), Decimal("1200"))
    app.operativa.agregar_tramo(adm, envio, "MARITIMO", BUENOS_AIRES, NUEVA_YORK, ids["buque"],
                                utc(4, 10, 6), utc(5, 1, 12), Decimal("6800"))
    app.trazabilidad.registrar_evento(adm, envio, "CARGA_INICIADA", "ARMDZ - bodega", "", utc(4, 7, 5))
    app.monitoreo.registrar_lectura(ids["sensor_dry"], {"lat": -33.3, "lon": -66.3, "bateria": 97}, utc(4, 8, 15))
    app.trazabilidad.registrar_evento(adm, envio, "EN_TRANSITO", "ARBUE - terminal 4", "Zarpó el buque", utc(4, 10, 7))
    incidente = app.trazabilidad.registrar_incidente(adm, envio, "CLIMA", "MEDIA",
                                                     "Temporal en el Atlántico: el buque reduce la velocidad",
                                                     utc(4, 20, 9))
    app.monitoreo.registrar_lectura(ids["sensor_dry"], {"lat": -5.0, "lon": -33.0, "bateria": 92}, utc(4, 20, 9))
    app.trazabilidad.cerrar_incidente(adm, incidente, utc(4, 25, 12))
    app.trazabilidad.registrar_evento(adm, envio, "ENTREGADO", "USNYC - Port Newark", "", utc(5, 4, 11))
    app.monitoreo.registrar_lectura(ids["sensor_dry"], {"lat": 40.68, "lon": -74.04, "bateria": 88}, utc(5, 4, 11))
    return envio


def cargar_envio_vencido(app: Aplicacion, adm: SesionActiva, ids: dict) -> int:
    envio = app.operativa.registrar_envio(adm, ids["pampa"], ROSARIO, SANTOS, "ALTA", 16000, 22,
                                          [ids["reefer"]], utc(9, 1, 9))
    app.operativa.agregar_tramo(adm, envio, "TERRESTRE", ROSARIO, BUENOS_AIRES, ids["camion"],
                                utc(9, 2, 6), utc(9, 3, 6), Decimal("800"))
    app.operativa.agregar_tramo(adm, envio, "MARITIMO", BUENOS_AIRES, SANTOS, ids["buque"],
                                utc(9, 4, 6), utc(9, 11, 18), Decimal("3200"))
    app.trazabilidad.registrar_evento(adm, envio, "CARGA_INICIADA", "ARROS - planta frigorífica", "", utc(9, 2, 5))
    app.trazabilidad.registrar_evento(adm, envio, "EN_TRANSITO", "ARBUE - terminal 4", "Zarpó el buque", utc(9, 4, 7))
    app.monitoreo.registrar_lectura(ids["sensor_reefer"], {"temperatura": 9.8, "humedad": 85, "lat": -28.5,
                                                           "lon": -47.8, "bateria": 90}, utc(9, 6, 14))
    return envio


def completar_clientes(app: Aplicacion, adm: SesionActiva) -> None:
    op = app.operativa
    clientes = {c["cuit"]: c for c in op.listar_clientes(adm)}
    contenedores = {c["codigo_internacional"]: c for c in op.listar_contenedores(adm)}
    envios_por_cliente = {}

    for envio in op.listar_envios(adm):
        if envio["contenedores"]:
            envios_por_cliente.setdefault(envio["cliente"]["id"], []).append(envio)

    camion = next(
        (v for v in op.listar_vehiculos(adm) if v["tipo"] == "CAMION" and v["estado"] == "ACTIVO"),
        None,
    )
    if camion is None:
        raise RuntimeError("No hay ningún camión activo para cargar los envíos de prueba")

    for numero, (razon_social, cuit, email, origen, destino) in enumerate(CLIENTES_ADICIONALES, start=1):
        telefono = f"+54 11 4000-{numero:04d}"
        cliente = clientes.get(cuit)
        if cliente is None:
            cliente_id = op.alta_cliente(
                adm, razon_social, cuit, email, telefono,
                f"Domicilio de prueba, {origen['ciudad']}", "AR",
            )
        else:
            cliente_id = cliente["id"]

        if cliente_id in envios_por_cliente:
            print(f"{razon_social}: ya tiene un envío con contenedor")
            continue

        codigo = f"CLTE{numero:07d}"
        contenedor = contenedores.get(codigo)
        if contenedor is None:
            contenedor_id = op.alta_contenedor(
                adm, codigo, "DRY", Decimal("33"), Decimal("-10"), Decimal("50")
            )
            op.alta_sensor(adm, "GPS", "Garmin", contenedor_id, utc(10, 1))
        else:
            contenedor_id = contenedor["id"]

        inicio = utc(10, 1, 8) + timedelta(days=(numero - 1) * 3)
        envio_id = op.registrar_envio(
            adm, cliente_id, origen, destino, "MEDIA", 3200, 18,
            [contenedor_id], inicio,
        )
        op.agregar_tramo(
            adm, envio_id, "TERRESTRE", origen, destino, camion["id"],
            inicio + timedelta(hours=2), inicio + timedelta(days=2), Decimal("1500"),
        )
        app.trazabilidad.registrar_evento(
            adm, envio_id, "CARGA_INICIADA", origen["codigo"],
            "Carga de mercadería preparada", inicio + timedelta(hours=1),
        )
        app.trazabilidad.registrar_evento(
            adm, envio_id, "EN_TRANSITO", origen["codigo"],
            "Camión en ruta", inicio + timedelta(hours=3),
        )
        if numero <= 4:
            app.trazabilidad.registrar_evento(
                adm, envio_id, "ENTREGADO", destino["codigo"],
                "Mercadería entregada", inicio + timedelta(days=2),
            )
        print(f"{razon_social}: cliente {cliente_id}, contenedor {contenedor_id}, envío {envio_id}")

    clientes_finales = op.listar_clientes(adm)
    envios_finales = op.listar_envios(adm)
    ids_con_contenedor = {
        e["cliente"]["id"] for e in envios_finales if e["contenedores"]
    }
    faltantes = [c["razon_social"] for c in clientes_finales if c["id"] not in ids_con_contenedor]
    print(f"Total de clientes: {len(clientes_finales)}")
    print(f"Clientes con envío y contenedor: {len(ids_con_contenedor)}")
    if faltantes:
        print("Clientes sin envío con contenedor: " + ", ".join(faltantes))


def cargar_comunicacion(app: Aplicacion, adm: SesionActiva, ids: dict, envio_vencido: int) -> None:
    app.mensajeria.enviar_privado(adm, ids["operador"],
                                  f"Revisá la alerta de temperatura del envío {envio_vencido}, por favor.", utc(9, 6, 15))
    grupo = app.mensajeria.crear_grupo(adm, "Seguimiento Brasil", True, [ids["operador"]])
    operador = app.auth.login(USUARIOS[1][1], USUARIOS[1][2])
    app.mensajeria.enviar_grupal(operador, grupo, "El reefer del envío a Santos superó los 8 °C. Ya avisé a la naviera.",
                                 utc(9, 6, 16))
    app.auth.logout(operador)


def cargar_facturacion(app: Aplicacion, adm: SesionActiva) -> None:
    primera = app.comercial.facturar_periodo(adm, "2026-02")["facturas"][0]["factura_id"]
    app.comercial.registrar_pago(adm, primera, Decimal("2000"), "TRANSFERENCIA", date(2026, 3, 15))
    segunda = app.comercial.facturar_periodo(adm, "2026-05")["facturas"][0]["factura_id"]
    app.comercial.registrar_pago(adm, segunda, Decimal("10000"), "TRANSFERENCIA", date(2026, 6, 10))
    for mes in range(1, 9):
        app.comercial.cierre_mensual(adm, f"2026-{mes:02d}")


def ejecutar_procesos(app: Aplicacion, adm: SesionActiva) -> None:
    app.sincronizacion.resincronizar_grafo(adm, completo=True)
    app.monitoreo.detectar_sensores_inactivos(adm)
    app.prediccion.predecir_riesgos(adm)


def cargar(app: Aplicacion) -> None:
    app.auth.crear_administrador_inicial("Ada", "Administradora", USUARIOS[0][1], USUARIOS[0][2], utc(1, 2))
    adm = app.auth.login(USUARIOS[0][1], USUARIOS[0][2])
    ids = cargar_maestros(app, adm)
    cargar_envio_a_tiempo(app, adm, ids)
    cargar_envio_tardio(app, adm, ids)
    envio_vencido = cargar_envio_vencido(app, adm, ids)
    cargar_comunicacion(app, adm, ids, envio_vencido)
    cargar_facturacion(app, adm)
    ejecutar_procesos(app, adm)
    completar_clientes(app, adm)
    app.auth.logout(adm)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--completar", action="store_true")
    args = parser.parse_args()
    app = crear_aplicacion()
    try:
        if args.completar:
            if not app.auth.hay_usuarios():
                print("No existen usuarios. Primero ejecutá python -m app.datos_prueba")
                sys.exit(1)
            adm = app.auth.login(USUARIOS[0][1], USUARIOS[0][2])
            try:
                completar_clientes(app, adm)
            finally:
                app.auth.logout(adm)
            print("Carga complementaria terminada")
            return
        if app.auth.hay_usuarios():
            print("Las bases ya tienen datos. Para cargarlos de nuevo desde cero:\n"
                  "  docker compose down -v\n  docker compose up -d\n"
                  "  python -m app.inicializar\n  python -m app.datos_prueba")
            sys.exit(1)
        cargar(app)
    except ErrorAplicacion as error:
        print(f"No se pudieron cargar los datos de prueba: {error}")
        sys.exit(1)
    except Exception:
        log.exception("Error técnico al cargar los datos de prueba")
        print("Error técnico al cargar los datos de prueba (¿están levantadas e inicializadas las bases?). "
              "Detalle en logistica.log.")
        sys.exit(1)
    finally:
        app.cerrar()
    if not args.completar:
        print("Datos de prueba cargados. Usuarios:")
        for rol, email, password in USUARIOS:
            print(f"  {rol:<28} {email:<34} {password}")


if __name__ == "__main__":
    main()
