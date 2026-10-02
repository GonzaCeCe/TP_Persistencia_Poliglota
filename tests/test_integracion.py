from datetime import timedelta
from decimal import Decimal

import pytest
from psycopg import sql

from app.datos_prueba import USUARIOS
from app.ensamblado import crear_aplicacion
from app.infra.errores import ErrorNegocio, IntegridadError, NoAutorizado

pytestmark = pytest.mark.integracion

UBICACION_ORIGEN = {"codigo": "ARBUE", "ciudad": "Buenos Aires", "pais": "AR"}
UBICACION_DESTINO = {"codigo": "BRSSZ", "ciudad": "Santos", "pais": "BR"}


@pytest.fixture(scope="module")
def app():
    aplicacion = crear_aplicacion()
    if not aplicacion.auth.hay_usuarios():
        aplicacion.cerrar()
        pytest.fail("Faltan los datos de prueba: ejecutá 'python -m app.datos_prueba' antes de los tests")
    yield aplicacion
    aplicacion.cerrar()


def _ingresar(app, indice_usuario: int):
    _, email, password = USUARIOS[indice_usuario]
    return app.auth.login(email, password)


@pytest.fixture(scope="module")
def admin(app):
    sesion = _ingresar(app, 0)
    yield sesion
    app.auth.logout(sesion)


@pytest.fixture(scope="module")
def usuario_cliente(app):
    sesion = _ingresar(app, 2)
    yield sesion
    app.auth.logout(sesion)


def _contar(app, tabla: str) -> int:
    consulta = sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(tabla))
    return app.conexiones.postgres().execute(consulta).fetchone()["n"]


def test_pago_que_excede_el_saldo_es_rechazado(app, admin):
    factura = next(f for cliente in app.operativa.listar_clientes(admin)
                   for f in app.comercial.estado_de_cuenta(admin, cliente_id=cliente["id"])["facturas"]
                   if f["pendiente"] > 0)
    pagos_antes = _contar(app, "pago")

    with pytest.raises(ErrorNegocio, match="supera el saldo pendiente"):
        app.comercial.registrar_pago(admin, factura["id"], factura["pendiente"] + Decimal("0.01"), "TRANSFERENCIA")

    assert _contar(app, "pago") == pagos_antes


def test_facturacion_idempotente_aunque_se_pierda_la_marca_en_mongo(app, admin):
    envio = next(e for e in app.operativa.listar_envios(admin) if e["facturado"])
    periodo = envio["fecha_entrega_real"].strftime("%Y-%m")
    facturas_antes, items_antes = _contar(app, "factura"), _contar(app, "factura_item")
    app.conexiones.mongo().envios.update_one({"_id": envio["_id"]}, {"$set": {"facturado": False, "factura_id": None}})

    resultado = app.comercial.facturar_periodo(admin, periodo)

    assert resultado["facturas"] == []
    assert envio["_id"] in resultado["reconciliados"]
    assert (_contar(app, "factura"), _contar(app, "factura_item")) == (facturas_antes, items_antes)
    reconciliado = app.operativa.ver_envio(admin, envio["_id"])
    assert (reconciliado["facturado"], reconciliado["factura_id"]) == (True, envio["factura_id"])


def test_contenedor_en_uso_no_se_puede_reservar(app, admin):
    en_uso = next(c for c in app.operativa.listar_contenedores(admin) if c["estado"] == "EN_USO")
    otro_cliente = next(c for c in app.operativa.listar_clientes(admin) if c["estado"] == "ACTIVO")
    envios_antes = len(app.operativa.listar_envios(admin))

    with pytest.raises(ErrorNegocio, match="no disponibles"):
        app.operativa.registrar_envio(admin, otro_cliente["id"], UBICACION_ORIGEN, UBICACION_DESTINO, "ALTA",
                                      1000, 1, [en_uso["id"]])

    assert len(app.operativa.listar_envios(admin)) == envios_antes
    estado_actual = next(c for c in app.operativa.listar_contenedores(admin) if c["id"] == en_uso["id"])["estado"]
    assert estado_actual == "EN_USO"


def test_alerta_abierta_no_se_duplica(app, admin):
    alerta = next(a for a in app.trazabilidad.alertas_abiertas(admin) if a["tipo"] == "TEMP_FUERA_RANGO")
    momento = alerta["fecha"] - timedelta(minutes=30)
    incidentes_antes = len(app.trazabilidad.incidentes_abiertos(admin))
    try:
        nuevas = app.monitoreo.registrar_lectura(alerta["sensor_id"], {"temperatura": 11.0}, momento)

        assert nuevas == []
        abiertas = [a for a in app.trazabilidad.alertas_abiertas(admin)
                    if a["sensor_id"] == alerta["sensor_id"] and a["tipo"] == "TEMP_FUERA_RANGO"]
        assert len(abiertas) == 1
        assert len(app.trazabilidad.incidentes_abiertos(admin)) == incidentes_antes
    finally:
        app.conexiones.mongo().lecturas.delete_many({"meta.sensor_id": alerta["sensor_id"], "fecha_hora": momento})


def test_control_de_integridad_devuelve_todo_vacio(app, admin):
    resultado = app.comercial.control_integridad(admin)

    assert resultado == {clave: [] for clave in resultado}
    assert len(resultado) == 3


def test_usuario_de_cliente_no_ve_envios_de_otro_cliente(app, admin, usuario_cliente):
    propios = app.operativa.listar_envios(usuario_cliente)
    ajeno = next(e for e in app.operativa.listar_envios(admin) if e["cliente"]["id"] != usuario_cliente.cliente_id)

    assert propios and all(e["cliente"]["id"] == usuario_cliente.cliente_id for e in propios)
    with pytest.raises(NoAutorizado):
        app.operativa.ver_envio(usuario_cliente, ajeno["_id"])
    with pytest.raises(NoAutorizado):
        app.trazabilidad.historial_eventos(usuario_cliente, ajeno["_id"])
    cuenta = app.comercial.estado_de_cuenta(usuario_cliente, cliente_id=ajeno["cliente"]["id"])["cuenta"]
    assert cuenta["cliente_id"] == usuario_cliente.cliente_id


def test_reintento_de_evento_no_lo_duplica(app, admin):
    envio = next(e for e in app.operativa.listar_envios(admin) if e["estado"] == "ENTREGADO")
    historial = app.trazabilidad.historial_eventos(admin, envio["_id"])
    evento, eventos_antes = historial[0], len(historial)

    with pytest.raises(IntegridadError, match="duplicado"):
        app.trazabilidad.registrar_evento(admin, envio["_id"], evento["tipo"], evento["ubicacion"],
                                          evento["descripcion"], evento["fecha_hora"])

    assert len(app.trazabilidad.historial_eventos(admin, envio["_id"])) == eventos_antes


def test_cierre_mensual_es_idempotente(app, admin):
    cierres_antes = _contar(app, "cierre_cc")

    assert app.comercial.cierre_mensual(admin, "2026-08") == 0
    assert _contar(app, "cierre_cc") == cierres_antes


def test_operacion_de_admin_rechazada_para_cliente(app, usuario_cliente):
    with pytest.raises(NoAutorizado):
        app.comercial.facturar_periodo(usuario_cliente, "2026-08")
