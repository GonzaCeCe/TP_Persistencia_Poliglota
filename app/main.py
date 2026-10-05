import getpass
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from app.ensamblado import Aplicacion, crear_aplicacion
from app.infra.errores import ErrorAplicacion, NoAutorizado
from app.servicios.auth import NIVEL_ADMIN, NIVEL_CLIENTE, NIVEL_OPERADOR, SesionActiva

log = logging.getLogger(__name__)

ANCHO_MAXIMO_CELDA = 40
Accion = Callable[[Aplicacion, SesionActiva], None]


class SesionTerminada(Exception):
    pass


@dataclass(frozen=True)
class Opcion:
    texto: str
    nivel: int
    destino: "Accion | list[Opcion]"


# Entrada de datos

def pedir_texto(etiqueta: str, obligatorio: bool = True, actual: str | None = None) -> str | None:
    sufijo = f" [{actual}]" if actual is not None else ("" if obligatorio else " (opcional)")
    while True:
        valor = input(f"  {etiqueta}{sufijo}: ").strip()
        if valor:
            return valor
        if actual is not None:
            return actual
        if not obligatorio:
            return None
        print("  Este dato es obligatorio.")


def _pedir_convertido(etiqueta: str, convertir: Callable, obligatorio: bool, formato: str = ""):
    while True:
        texto = pedir_texto(f"{etiqueta}{formato}", obligatorio)
        if texto is None:
            return None
        try:
            return convertir(texto)
        except (ValueError, InvalidOperation):
            print("  Valor inválido, probá de nuevo.")


def pedir_entero(etiqueta: str, obligatorio: bool = True) -> int | None:
    return _pedir_convertido(etiqueta, int, obligatorio)


def pedir_numero(etiqueta: str, obligatorio: bool = True) -> float | None:
    return _pedir_convertido(etiqueta, lambda t: float(t.replace(",", ".")), obligatorio)


def pedir_decimal(etiqueta: str, obligatorio: bool = True) -> Decimal | None:
    return _pedir_convertido(etiqueta, lambda t: Decimal(t.replace(",", ".")), obligatorio)


def _a_fecha_hora(texto: str) -> datetime:
    formato = "%Y-%m-%d %H:%M" if " " in texto else "%Y-%m-%d"
    return datetime.strptime(texto, formato).replace(tzinfo=timezone.utc)


def pedir_fecha_hora(etiqueta: str, obligatorio: bool = False, si_vacio: str = "ahora") -> datetime | None:
    vacio = "" if obligatorio else f", vacío = {si_vacio}"
    return _pedir_convertido(etiqueta, _a_fecha_hora, obligatorio, f" (AAAA-MM-DD [HH:MM] UTC{vacio})")


def pedir_fecha(etiqueta: str, obligatorio: bool = False) -> date | None:
    vacio = "" if obligatorio else ", vacío = hoy"
    return _pedir_convertido(etiqueta, lambda t: datetime.strptime(t, "%Y-%m-%d").date(), obligatorio,
                             f" (AAAA-MM-DD{vacio})")


def pedir_lista_de_enteros(etiqueta: str) -> list[int]:
    return _pedir_convertido(etiqueta, lambda t: [int(x) for x in t.replace(" ", "").split(",") if x], True,
                             " (separados por coma)")


def elegir(etiqueta: str, opciones: tuple[str, ...] | list[str], actual: str | None = None) -> str:
    print(f"  {etiqueta}:")
    for numero, opcion in enumerate(opciones, start=1):
        print(f"    {numero}. {opcion}")
    while True:
        texto = input(f"  Opción{f' [{actual}]' if actual else ''}: ").strip()
        if not texto and actual is not None:
            return actual
        if texto.isdigit() and 1 <= int(texto) <= len(opciones):
            return opciones[int(texto) - 1]
        print("  Opción inválida.")


def confirmar(pregunta: str) -> bool:
    return input(f"  {pregunta} (s/n): ").strip().lower() in ("s", "si", "sí")


def pedir_ubicacion(etiqueta: str) -> dict:
    print(f"  {etiqueta}:")
    return {"codigo": pedir_texto("  Código UN/LOCODE (ej. ARBUE)"), "ciudad": pedir_texto("  Ciudad"),
            "pais": pedir_texto("  País (2 letras)")}


# Salida de datos

def formatear(valor) -> str:
    if valor is None:
        return "-"
    if hasattr(valor, "to_native"):
        valor = valor.to_native()
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if isinstance(valor, datetime):
        return valor.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, float):
        return f"{valor:.2f}".rstrip("0").rstrip(".")
    if isinstance(valor, (list, tuple, set)):
        return ", ".join(formatear(v) for v in valor)
    if isinstance(valor, dict):
        return ", ".join(f"{k}={formatear(v)}" for k, v in valor.items())
    return str(valor)


def _recortar(texto: str) -> str:
    return texto if len(texto) <= ANCHO_MAXIMO_CELDA else texto[:ANCHO_MAXIMO_CELDA - 1] + "…"


def mostrar_tabla(filas: list[dict], columnas: list[str] | tuple[str, ...] | None = None) -> None:
    if not filas:
        print("  (sin resultados)")
        return
    columnas = list(columnas or filas[0].keys())
    celdas = [[_recortar(formatear(fila.get(columna))) for columna in columnas] for fila in filas]
    anchos = [max(len(columna), *(len(fila[i]) for fila in celdas)) for i, columna in enumerate(columnas)]
    print("  " + " | ".join(c.ljust(a) for c, a in zip(columnas, anchos)))
    print("  " + "-+-".join("-" * a for a in anchos))
    for fila in celdas:
        print("  " + " | ".join(c.ljust(a) for c, a in zip(fila, anchos)))
    print(f"  ({len(filas)} filas)")


def mostrar_detalle(datos: dict, campos: list[str] | None = None) -> None:
    for campo in campos or datos:
        print(f"  {campo:<24} {formatear(datos.get(campo))}")


def titulo(texto: str) -> None:
    print(f"\n=== {texto} ===")


def ok(mensaje: str) -> None:
    print(f"  OK: {mensaje}")


# Clientes y empresas

def listar_clientes(app, sesion):
    mostrar_tabla(app.operativa.listar_clientes(sesion),
                  ["id", "razon_social", "cuit", "email", "telefono", "pais", "estado"])


def alta_cliente(app, sesion):
    cliente_id = app.operativa.alta_cliente(
        sesion, pedir_texto("Razón social"), pedir_texto("CUIT (NN-NNNNNNNN-N)"), pedir_texto("Email"),
        pedir_texto("Teléfono", False), pedir_texto("Dirección", False), pedir_texto("País (2 letras)"))
    ok(f"cliente {cliente_id} creado con su cuenta corriente")


def modificar_cliente(app, sesion):
    cliente = app.operativa.ver_cliente(sesion, pedir_entero("Id de cliente"))
    print("  Enter conserva el valor actual.")
    nuevos = {campo: pedir_texto(campo, actual=cliente[campo] or "")
              for campo in ("razon_social", "email", "telefono", "direccion", "pais")}
    nuevos["estado"] = elegir("Estado", ("ACTIVO", "INACTIVO"), cliente["estado"])
    cambios = {campo: valor for campo, valor in nuevos.items() if valor != (cliente[campo] or "")}
    app.operativa.modificar_cliente(sesion, cliente["id"], cambios)
    ok(f"cliente modificado ({', '.join(cambios) or 'sin cambios'})")


def baja_cliente(app, sesion):
    cliente = app.operativa.ver_cliente(sesion, pedir_entero("Id de cliente"))
    if confirmar(f"¿Dar de baja a {cliente['razon_social']}?"):
        app.operativa.baja_cliente(sesion, cliente["id"])
        ok("cliente dado de baja (baja lógica)")


def listar_empresas(app, sesion):
    mostrar_tabla(app.operativa.listar_empresas(sesion), ["id", "tipo", "razon_social", "cuit", "pais", "estado"])


def alta_empresa(app, sesion):
    empresa_id = app.operativa.alta_empresa(sesion, elegir("Tipo", ("OPERADOR", "PROVEEDOR")),
                                            pedir_texto("Razón social"), pedir_texto("CUIT (NN-NNNNNNNN-N)"),
                                            pedir_texto("País (2 letras)"))
    ok(f"empresa {empresa_id} creada con su cuenta corriente")


def modificar_empresa(app, sesion):
    empresa_id = pedir_entero("Id de empresa")
    empresa = next((e for e in app.operativa.listar_empresas(sesion) if e["id"] == empresa_id), None)
    if empresa is None:
        print("  La empresa no existe.")
        return
    print("  Enter conserva el valor actual.")
    nuevos = {"razon_social": pedir_texto("razon_social", actual=empresa["razon_social"]),
              "pais": pedir_texto("pais", actual=empresa["pais"]),
              "estado": elegir("Estado", ("ACTIVO", "INACTIVO"), empresa["estado"])}
    cambios = {campo: valor for campo, valor in nuevos.items() if valor != empresa[campo]}
    app.operativa.modificar_empresa(sesion, empresa_id, cambios)
    ok(f"empresa modificada ({', '.join(cambios) or 'sin cambios'})")


def baja_empresa(app, sesion):
    empresa_id = pedir_entero("Id de empresa")
    if confirmar(f"¿Dar de baja la empresa {empresa_id}?"):
        app.operativa.baja_empresa(sesion, empresa_id)
        ok("empresa dada de baja (baja lógica)")


# Usuarios y sesiones

def listar_usuarios(app, sesion):
    mostrar_tabla(app.auth.listar_usuarios(sesion),
                  ["id", "nombre", "apellido", "email", "cliente_id", "roles", "estado", "fecha_registro"])


def alta_usuario(app, sesion):
    nombre, apellido, email = pedir_texto("Nombre"), pedir_texto("Apellido"), pedir_texto("Email")
    password = pedir_password()
    if elegir("Tipo de usuario", ("Interno", "De un cliente")) == "Interno":
        roles, cliente_id = [elegir("Rol", ("ADMIN", "OPERADOR"))], None
    else:
        roles, cliente_id = ["CLIENTE"], pedir_entero("Id de cliente")
    usuario_id = app.auth.registrar_usuario(sesion, nombre, apellido, email, password, roles, cliente_id)
    ok(f"usuario {usuario_id} creado")


def leer_secreto(etiqueta: str) -> str:
    return getpass.getpass(etiqueta) if sys.stdin.isatty() else input(etiqueta)


def pedir_password() -> str:
    while True:
        password = leer_secreto("  Contraseña (mínimo 8 caracteres): ")
        if password == leer_secreto("  Repetir contraseña: "):
            return password
        print("  Las contraseñas no coinciden.")


def asignar_rol(app, sesion):
    usuario_id = pedir_entero("Id de usuario")
    app.auth.asignar_rol(sesion, usuario_id, elegir("Rol", ("ADMIN", "OPERADOR", "CLIENTE")))
    ok("rol asignado (se aplica en el próximo ingreso del usuario)")


def cambiar_estado_usuario(app, sesion):
    usuario_id = pedir_entero("Id de usuario")
    estado = elegir("Nuevo estado", ("ACTIVO", "BLOQUEADO", "BAJA"))
    app.auth.cambiar_estado_usuario(sesion, usuario_id, estado)
    ok(f"usuario {usuario_id} en estado {estado}")


def mis_sesiones(app, sesion):
    mostrar_tabla(app.auth.mis_sesiones(sesion), ["id", "fecha_inicio", "actual"])


def cerrar_sesiones_de_usuario(app, sesion):
    usuario_id = sesion.usuario_id
    if sesion.nivel >= NIVEL_ADMIN:
        usuario_id = pedir_entero(f"Id de usuario (vacío = vos, {sesion.usuario_id})", False) or sesion.usuario_id
    if confirmar(f"¿Cerrar todas las sesiones del usuario {usuario_id}?"):
        ok(f"{app.auth.cerrar_sesiones_de_usuario(sesion, usuario_id)} sesiones cerradas")


def directorio(app, sesion):
    mostrar_tabla(app.auth.directorio(sesion))


# Contenedores, sensores y vehículos

def listar_contenedores(app, sesion):
    mostrar_tabla(app.operativa.listar_contenedores(sesion))


def alta_contenedor(app, sesion):
    contenedor_id = app.operativa.alta_contenedor(
        sesion, pedir_texto("Código ISO 6346 (4 letras y 7 dígitos)"), elegir("Tipo", ("DRY", "REEFER", "TANK", "OPEN_TOP")),
        pedir_decimal("Capacidad (m3)"), pedir_decimal("Temperatura mínima (°C)"), pedir_decimal("Temperatura máxima (°C)"))
    ok(f"contenedor {contenedor_id} creado")


def cambiar_estado_contenedor(app, sesion):
    contenedor_id = pedir_entero("Id de contenedor")
    estado = elegir("Nuevo estado", ("DISPONIBLE", "MANTENIMIENTO", "BAJA"))
    app.operativa.cambiar_estado_contenedor(sesion, contenedor_id, estado)
    ok(f"contenedor {contenedor_id} en estado {estado}")


def alta_sensor(app, sesion):
    sensor_id = app.operativa.alta_sensor(sesion, elegir("Tipo", ("TEMPERATURA", "HUMEDAD", "VIBRACION", "GPS", "MULTI")),
                                          pedir_texto("Fabricante"), pedir_entero("Id de contenedor", False),
                                          pedir_fecha_hora("Fecha de instalación"))
    ok(f"sensor {sensor_id} creado")


def asociar_sensor(app, sesion):
    sensor_id = pedir_entero("Id de sensor")
    contenedor_id = pedir_entero("Id de contenedor")
    app.operativa.asociar_sensor(sesion, sensor_id, contenedor_id)
    ok(f"sensor {sensor_id} asociado al contenedor {contenedor_id}")


def cambiar_estado_sensor(app, sesion):
    sensor_id = pedir_entero("Id de sensor")
    estado = elegir("Nuevo estado", ("ACTIVO", "INACTIVO", "FALLA", "BAJA"))
    app.operativa.cambiar_estado_sensor(sesion, sensor_id, estado)
    ok(f"sensor {sensor_id} en estado {estado}")


def listar_vehiculos(app, sesion):
    mostrar_tabla(app.operativa.listar_vehiculos(sesion), ["id", "tipo", "identificacion", "empresa_id", "razon_social", "estado"])


def alta_vehiculo(app, sesion):
    operadores = [e for e in app.operativa.listar_empresas(sesion) if e["tipo"] == "OPERADOR" and e["estado"] == "ACTIVO"]
    mostrar_tabla(operadores, ["id", "razon_social"])
    vehiculo_id = app.operativa.alta_vehiculo(sesion, elegir("Tipo", ("CAMION", "TREN", "BUQUE", "AVION")),
                                              pedir_texto("Identificación (patente, IMO, matrícula)"),
                                              pedir_entero("Id del operador"))
    ok(f"vehículo {vehiculo_id} creado")


# Envíos y tramos

def listar_envios(app, sesion):
    mostrar_tabla([{**e, "cliente": e["cliente"]["razon_social"], "origen": e["origen"]["codigo"],
                    "destino": e["destino"]["codigo"], "tramos": len(e["tramos"])}
                   for e in app.operativa.listar_envios(sesion, pedir_texto("País de destino (2 letras)", False))],
                  ["_id", "cliente", "origen", "destino", "estado", "prioridad", "tramos", "fecha_entrega_estimada",
                   "fecha_entrega_real", "facturado"])


def ver_envio(app, sesion):
    envio = app.operativa.ver_envio(sesion, pedir_entero("Id de envío"))
    mostrar_detalle({**envio, "cliente": envio["cliente"]["razon_social"],
                     "contenedores": [c["codigo"] for c in envio["contenedores"]]},
                    ["_id", "cliente", "fecha_creacion", "origen", "destino", "estado", "prioridad", "peso_kg",
                     "volumen_m3", "contenedores", "fecha_entrega_estimada", "fecha_entrega_real",
                     "cantidad_incidentes", "ultimo_evento", "facturado", "factura_id", "grafo_sincronizado"])
    print("  Tramos:")
    mostrar_tabla(_filas_de_tramos(envio["tramos"]))


def _filas_de_tramos(tramos: list[dict]) -> list[dict]:
    return [{"id": t["id"], "medio": t["medio"], "origen": t["origen"]["codigo"], "destino": t["destino"]["codigo"],
             "operador": t["operador"]["razon_social"], "vehiculo": t["vehiculo"]["identificacion"],
             "salida": t["fecha_salida"], "llegada_estimada": t["fecha_llegada_estimada"], "costo": t["costo"]}
            for t in tramos]


def registrar_envio(app, sesion):
    cliente_id = pedir_entero("Id de cliente")
    origen, destino = pedir_ubicacion("Origen"), pedir_ubicacion("Destino")
    prioridad = elegir("Prioridad", ("BAJA", "MEDIA", "ALTA"))
    peso, volumen = pedir_numero("Peso (kg)"), pedir_numero("Volumen (m3)")
    disponibles = [c for c in app.operativa.listar_contenedores(sesion) if c["estado"] == "DISPONIBLE"]
    mostrar_tabla(disponibles, ["id", "codigo_internacional", "tipo", "capacidad_m3", "temp_min", "temp_max"])
    contenedores = pedir_lista_de_enteros("Ids de contenedores")
    envio_id = app.operativa.registrar_envio(sesion, cliente_id, origen, destino, prioridad, peso, volumen,
                                             contenedores, pedir_fecha_hora("Fecha de creación"))
    ok(f"envío {envio_id} registrado; contenedores reservados")


def agregar_tramo(app, sesion):
    envio = app.operativa.ver_envio(sesion, pedir_entero("Id de envío"))
    mostrar_tabla(_filas_de_tramos(envio["tramos"]))
    medio = elegir("Medio de transporte", ("TERRESTRE", "MARITIMO", "AEREO"))
    origen, destino = pedir_ubicacion("Origen del tramo"), pedir_ubicacion("Destino del tramo")
    listar_vehiculos(app, sesion)
    tramo_id = app.operativa.agregar_tramo(sesion, envio["_id"], medio, origen, destino, pedir_entero("Id de vehículo"),
                                           pedir_fecha_hora("Salida", True), pedir_fecha_hora("Llegada estimada", True),
                                           pedir_decimal("Costo"))
    ok(f"tramo {tramo_id} agregado")


def cancelar_envio(app, sesion):
    envio_id = pedir_entero("Id de envío")
    if confirmar(f"¿Cancelar el envío {envio_id}?"):
        app.operativa.cancelar_envio(sesion, envio_id)
        ok("envío cancelado y contenedores liberados")


# Monitoreo

def registrar_lectura(app, sesion):
    sensor_id = pedir_entero("Id de sensor")
    print("  Dejá vacías las medidas que el sensor no reporta.")
    medidas = {nombre: pedir_numero(nombre, False) for nombre in ("temperatura", "humedad", "vibracion", "lat", "lon", "bateria")}
    alertas = app.monitoreo.registrar_lectura(sensor_id, medidas, pedir_fecha_hora("Fecha y hora"))
    ok("lectura registrada")
    for alerta in alertas:
        incidente = f", incidente {alerta['incidente_id']} creado" if alerta.get("incidente_id") else ""
        print(f"  ALERTA {alerta['_id']}: {alerta['tipo']} valor {alerta['valor']} (umbral {alerta['umbral']}){incidente}")


def historial_lecturas(app, sesion):
    lecturas = app.monitoreo.historial_lecturas(sesion, pedir_entero("Id de sensor"),
                                                pedir_fecha_hora("Desde", True), pedir_fecha_hora("Hasta", True))
    mostrar_tabla(lecturas, ["fecha_hora", "temperatura", "humedad", "vibracion", "lat", "lon", "bateria"])


def exportar_geojson(app, sesion):
    archivo, puntos = app.monitoreo.exportar_recorrido_geojson(sesion, pedir_entero("Id de contenedor"))
    ok(f"{puntos} posiciones exportadas a {archivo}")
    print("  Para verlo en un mapa, abrí https://geojson.io y arrastrá el archivo.")


def contenedores_cercanos(app, sesion):
    mostrar_tabla(app.monitoreo.contenedores_cercanos(sesion, pedir_numero("Latitud"), pedir_numero("Longitud"),
                                                      pedir_numero("Radio (km)")))


def estado_sensores(app, sesion):
    mostrar_tabla([{**s, "codigo": s["codigo_internacional"], "ultima": s["ultima_lectura"].get("fecha_hora", "")[:16],
                    "temperatura": s["ultima_lectura"].get("temperatura"), "bateria": s["ultima_lectura"].get("bateria")}
                   for s in app.monitoreo.estado_sensores(sesion)],
                  ["id", "tipo", "contenedor_id", "codigo", "estado", "reportando", "ultima", "temperatura", "bateria"])


# Trazabilidad

def registrar_evento(app, sesion):
    envio_id = pedir_entero("Id de envío")
    tipo = elegir("Tipo de evento", ("CARGA_INICIADA", "EN_TRANSITO", "ADUANA", "RETRASO", "DESCARGA", "ENTREGADO"))
    resultado = app.trazabilidad.registrar_evento(sesion, envio_id, tipo, pedir_texto("Ubicación"),
                                                  pedir_texto("Descripción", False) or "", pedir_fecha_hora("Fecha y hora"))
    if resultado["estado_actualizado"]:
        ok(f"evento registrado; el envío quedó {resultado['estado']}")
    else:
        ok(f"evento registrado en el historial; no es el más reciente, el envío sigue {resultado['estado']}")


def historial_eventos(app, sesion):
    mostrar_tabla(app.trazabilidad.historial_eventos(sesion, pedir_entero("Id de envío")),
                  ["fecha_hora", "tipo", "ubicacion", "descripcion"])


def seguimiento_envio(app, sesion):
    seguimiento = app.trazabilidad.seguimiento_envio(sesion, pedir_entero("Id de envío"))
    envio = seguimiento["envio"]
    print(f"  Envío {envio['_id']} {envio['origen']['codigo']} -> {envio['destino']['codigo']}: {envio['estado']}"
          f"{' (DEMORADO)' if seguimiento['demorado'] else ''}")
    mostrar_tabla(seguimiento["linea_de_tiempo"])


def recorrido_contenedor(app, sesion):
    recorrido = app.trazabilidad.recorrido_contenedor(sesion, pedir_entero("Id de contenedor"))
    print(f"  Contenedor {recorrido['contenedor']['codigo_internacional']}")
    mostrar_tabla(recorrido["posiciones"], ["fecha_hora", "lat", "lon", "temperatura"])


def movimientos_contenedor(app, sesion):
    movimientos = app.trazabilidad.movimientos_contenedor(sesion, pedir_entero("Id de contenedor"))
    print(f"  Contenedor {movimientos['contenedor']['codigo_internacional']} — envíos:")
    mostrar_tabla([{**e, "origen": e["origen"]["codigo"], "destino": e["destino"]["codigo"]} for e in movimientos["envios"]],
                  ["_id", "origen", "destino", "estado", "fecha_creacion", "fecha_entrega_real"])
    print("  Eventos:")
    mostrar_tabla(movimientos["eventos"], ["fecha_hora", "envio_id", "tipo", "ubicacion", "descripcion"])


def registrar_incidente(app, sesion):
    incidente_id = app.trazabilidad.registrar_incidente(
        sesion, pedir_entero("Id de envío"), pedir_texto("Tipo (ej. DAÑO, ROBO, CLIMA)"),
        elegir("Severidad", ("BAJA", "MEDIA", "ALTA", "CRITICA")), pedir_texto("Descripción"), pedir_fecha_hora("Fecha"))
    ok(f"incidente {incidente_id} registrado")


def cerrar_incidente(app, sesion):
    incidente_id = pedir_entero("Id de incidente")
    app.trazabilidad.cerrar_incidente(sesion, incidente_id, pedir_fecha_hora("Fecha de cierre"))
    ok(f"incidente {incidente_id} cerrado")


def incidentes_abiertos(app, sesion):
    mostrar_tabla(app.trazabilidad.incidentes_abiertos(sesion),
                  ["_id", "envio_id", "tramo_id", "ruta", "tipo", "severidad", "fecha", "descripcion"])


def alertas_abiertas(app, sesion):
    mostrar_tabla(app.trazabilidad.alertas_abiertas(sesion),
                  ["_id", "tipo", "sensor_id", "contenedor_id", "envio_id", "fecha", "valor", "umbral"])


def cerrar_alerta(app, sesion):
    alerta_id = pedir_entero("Id de alerta")
    app.trazabilidad.cerrar_alerta(sesion, alerta_id)
    ok(f"alerta {alerta_id} cerrada")


# Comunicación

def enviar_privado(app, sesion):
    directorio(app, sesion)
    destinatario = pedir_entero("Id del destinatario")
    conversacion = app.mensajeria.enviar_privado(sesion, destinatario, pedir_texto("Mensaje"))
    ok(f"mensaje enviado (conversación {conversacion})")


def ver_grupos(app, sesion):
    grupos = app.mensajeria.grupos(sesion)
    for nombre, lista in (("Mis grupos", grupos["mis_grupos"]), ("Grupos públicos", grupos["publicos"])):
        print(f"  {nombre}:")
        mostrar_tabla([{"id": g["_id"], "nombre": g["nombre"], "publico": g["publico"],
                        "integrantes": [i["usuario_id"] for i in g["integrantes"]]} for g in lista])


def crear_grupo(app, sesion):
    directorio(app, sesion)
    grupo_id = app.mensajeria.crear_grupo(sesion, pedir_texto("Nombre del grupo"), confirmar("¿Es público?"),
                                          pedir_lista_de_enteros("Ids de integrantes (vos ya estás incluido)"))
    ok(f"grupo {grupo_id} creado")


def unirse_a_grupo(app, sesion):
    ver_grupos(app, sesion)
    grupo_id = pedir_entero("Id del grupo público")
    app.mensajeria.unirse_a_grupo(sesion, grupo_id)
    ok(f"te uniste al grupo {grupo_id}")


def enviar_grupal(app, sesion):
    ver_grupos(app, sesion)
    grupo_id = pedir_entero("Id del grupo")
    conversacion = app.mensajeria.enviar_grupal(sesion, grupo_id, pedir_texto("Mensaje"))
    ok(f"mensaje enviado (conversación {conversacion})")


def mis_conversaciones(app, sesion):
    mostrar_tabla(app.mensajeria.mis_conversaciones(sesion))


def historial_conversacion(app, sesion):
    mostrar_tabla(app.mensajeria.historial_conversacion(sesion, pedir_texto("Id de conversación (ej. u1-u3 o g1)")),
                  ["fecha_hora", "remitente_id", "contenido"])


def monitor_de_alertas(app, sesion):
    print("  Escuchando alertas en tiempo real. Ctrl+C para volver al menú.")
    try:
        for alerta in app.monitoreo.escuchar_alertas(sesion):
            print(f"  [{alerta['fecha'][:19]}] ALERTA {alerta['_id']} {alerta['tipo']} sensor {alerta['sensor_id']} "
                  f"contenedor {alerta['contenedor_id']} envío {alerta['envio_id']} valor {alerta['valor']}")
    except KeyboardInterrupt:
        print("\n  Monitor detenido.")


# Gestión comercial

def solicitar_reporte(app, sesion):
    tipos = list(app.reportes.tipos)
    tipo = elegir("Reporte", [f"{t} — {app.reportes.tipos[t].descripcion}" for t in tipos]).split(" — ")[0]
    desde = pedir_fecha_hora("Desde", si_vacio="sin límite")
    hasta = pedir_fecha_hora("Hasta", si_vacio="sin límite")
    resultado = app.reportes.solicitar_reporte(sesion, tipo, desde, hasta, elegir("Formato", ("JSON", "CSV")))
    mostrar_tabla(resultado["filas"], resultado["columnas"])
    ok(f"reporte {resultado['reporte_id']} guardado en {resultado['archivo']}")


def registrar_pago(app, sesion):
    resultado = app.comercial.registrar_pago(sesion, pedir_entero("Id de factura"), pedir_decimal("Monto"),
                                             elegir("Medio de pago", ("TRANSFERENCIA", "TARJETA", "CHEQUE", "EFECTIVO")),
                                             pedir_fecha("Fecha del pago"))
    ok(f"pago {resultado['pago_id']} registrado; factura {resultado['estado_factura']}, "
       f"pendiente {resultado['saldo_pendiente']}")


def estado_de_cuenta(app, sesion):
    if sesion.cliente_id is not None:
        estado = app.comercial.estado_de_cuenta(sesion)
    else:
        mostrar_tabla(app.comercial.listar_cuentas(sesion), ["id", "tipo_titular", "cliente_id", "empresa_id", "titular", "saldo"])
        titular = elegir("Titular", ("Cliente", "Empresa"))
        titular_id = pedir_entero(f"Id de {titular.lower()}")
        estado = app.comercial.estado_de_cuenta(sesion, **{"cliente_id" if titular == "Cliente" else "empresa_id": titular_id})
    print(f"  Cuenta {estado['cuenta']['id']} — saldo {estado['cuenta']['saldo']} (positivo = deuda del titular)")
    print("  Movimientos:")
    mostrar_tabla(estado["movimientos"], ["fecha", "tipo", "importe", "factura_id", "pago_id", "envio_id", "descripcion"])
    if estado["facturas"]:
        print("  Facturas:")
        mostrar_tabla(estado["facturas"], ["id", "periodo", "fecha_emision", "importe_total", "pagado", "pendiente", "estado"])
    print("  Cierres mensuales:")
    mostrar_tabla(estado["cierres"], ["periodo", "saldo_inicial", "total_debe", "total_haber", "saldo_final"])


# Consultas avanzadas

def ruta_completa(app, sesion):
    ruta = app.trazabilidad.ruta_completa(sesion, pedir_entero("Id de envío"))
    if not ruta["grafo_sincronizado"]:
        print("  Aviso: el envío tiene cambios pendientes de proyectar al grafo (Procesos > Resincronizar grafo).")
    mostrar_tabla(ruta["tramos"])


def red_de_relaciones(app, sesion):
    red = app.trazabilidad.red_de_relaciones(sesion)
    print("  Clientes, operadores y envíos:")
    mostrar_tabla(red["red"])
    print("  Clientes que comparten operador:")
    mostrar_tabla(red["comparten_operador"])


def impacto_de_ubicacion(app, sesion):
    mostrar_tabla(app.trazabilidad.impacto_de_ubicacion(sesion, pedir_texto("Código de ubicación (ej. BRSSZ)")))


def predicciones_del_dia(app, sesion):
    mostrar_tabla(app.prediccion.predicciones_del_dia(sesion, pedir_fecha("Día")),
                  ["envio_id", "dia", "probabilidad_demora", "riesgo_operativo", "riesgo_climatico", "factores"])


def predicciones_de_envio(app, sesion):
    mostrar_tabla(app.prediccion.predicciones_de_envio(sesion, pedir_entero("Id de envío")),
                  ["dia", "probabilidad_demora", "riesgo_operativo", "riesgo_climatico", "factores"])


# Procesos periódicos

def facturar_periodo(app, sesion):
    resultado = app.comercial.facturar_periodo(sesion, pedir_texto("Período (AAAA-MM)"))
    mostrar_tabla(resultado["facturas"])
    ok(f"{len(resultado['facturas'])} facturas emitidas; reconciliados: {resultado['reconciliados'] or 'ninguno'}")


def cierre_mensual(app, sesion):
    ok(f"{app.comercial.cierre_mensual(sesion, pedir_texto('Período (AAAA-MM)'))} cuentas cerradas "
       "(0 = el período ya estaba cerrado)")


def detectar_sensores_inactivos(app, sesion):
    inactivos = app.monitoreo.detectar_sensores_inactivos(sesion)
    mostrar_tabla(inactivos, ["id", "tipo", "contenedor_id", "fecha_instalacion"])
    ok(f"{len(inactivos)} sensores pasaron a INACTIVO")


def prediccion_diaria(app, sesion):
    predicciones = app.prediccion.predecir_riesgos(sesion)
    mostrar_tabla(predicciones, ["envio_id", "dia", "probabilidad_demora", "riesgo_operativo", "riesgo_climatico"])


def reconciliar_sesiones(app, sesion):
    ok(f"{app.auth.reconciliar_sesiones(sesion)} sesiones marcadas como EXPIRADA")


def resincronizar_grafo(app, sesion):
    completo = elegir("Modo", ("Solo pendientes", "Reconstruir todo")) == "Reconstruir todo"
    resultado = app.sincronizacion.resincronizar_grafo(sesion, completo)
    ok(f"{resultado['envios']} envíos y {resultado['clientes']} clientes proyectados ({resultado['modo']})")


def control_de_integridad(app, sesion):
    resultado = app.comercial.control_integridad(sesion)
    for control, filas in resultado.items():
        print(f"  {control}:")
        mostrar_tabla(filas)
    ok("sin inconsistencias" if not any(resultado.values()) else "se encontraron inconsistencias")


# Menú

MENU = [
    Opcion("Clientes y empresas", NIVEL_OPERADOR, [
        Opcion("Listar clientes", NIVEL_OPERADOR, listar_clientes),
        Opcion("Alta de cliente", NIVEL_OPERADOR, alta_cliente),
        Opcion("Modificar cliente", NIVEL_OPERADOR, modificar_cliente),
        Opcion("Baja de cliente", NIVEL_OPERADOR, baja_cliente),
        Opcion("Listar empresas (operadores y proveedores)", NIVEL_OPERADOR, listar_empresas),
        Opcion("Alta de empresa", NIVEL_OPERADOR, alta_empresa),
        Opcion("Modificar empresa", NIVEL_OPERADOR, modificar_empresa),
        Opcion("Baja de empresa", NIVEL_OPERADOR, baja_empresa),
    ]),
    Opcion("Usuarios y sesiones", NIVEL_CLIENTE, [
        Opcion("Mis sesiones activas", NIVEL_CLIENTE, mis_sesiones),
        Opcion("Cerrar todas las sesiones de un usuario", NIVEL_CLIENTE, cerrar_sesiones_de_usuario),
        Opcion("Listar usuarios", NIVEL_ADMIN, listar_usuarios),
        Opcion("Alta de usuario", NIVEL_ADMIN, alta_usuario),
        Opcion("Asignar rol", NIVEL_ADMIN, asignar_rol),
        Opcion("Cambiar estado de usuario", NIVEL_ADMIN, cambiar_estado_usuario),
    ]),
    Opcion("Contenedores, sensores y vehículos", NIVEL_OPERADOR, [
        Opcion("Listar contenedores", NIVEL_OPERADOR, listar_contenedores),
        Opcion("Alta de contenedor", NIVEL_OPERADOR, alta_contenedor),
        Opcion("Cambiar estado de contenedor", NIVEL_OPERADOR, cambiar_estado_contenedor),
        Opcion("Alta de sensor", NIVEL_OPERADOR, alta_sensor),
        Opcion("Asociar sensor a contenedor", NIVEL_OPERADOR, asociar_sensor),
        Opcion("Cambiar estado de sensor", NIVEL_OPERADOR, cambiar_estado_sensor),
        Opcion("Listar vehículos", NIVEL_OPERADOR, listar_vehiculos),
        Opcion("Alta de vehículo", NIVEL_OPERADOR, alta_vehiculo),
    ]),
    Opcion("Envíos y tramos", NIVEL_CLIENTE, [
        Opcion("Listar envíos", NIVEL_CLIENTE, listar_envios),
        Opcion("Ver envío", NIVEL_CLIENTE, ver_envio),
        Opcion("Registrar envío", NIVEL_OPERADOR, registrar_envio),
        Opcion("Agregar tramo", NIVEL_OPERADOR, agregar_tramo),
        Opcion("Cancelar envío", NIVEL_OPERADOR, cancelar_envio),
    ]),
    Opcion("Monitoreo IoT", NIVEL_OPERADOR, [
        Opcion("Registrar lectura manual", NIVEL_OPERADOR, registrar_lectura),
        Opcion("Historial de lecturas de un sensor", NIVEL_OPERADOR, historial_lecturas),
        Opcion("Exportar recorrido de un contenedor (GeoJSON)", NIVEL_OPERADOR, exportar_geojson),
        Opcion("Contenedores dentro de un radio", NIVEL_OPERADOR, contenedores_cercanos),
        Opcion("Estado de sensores", NIVEL_OPERADOR, estado_sensores),
    ]),
    Opcion("Trazabilidad e incidentes", NIVEL_CLIENTE, [
        Opcion("Registrar evento logístico", NIVEL_OPERADOR, registrar_evento),
        Opcion("Historial de eventos de un envío", NIVEL_CLIENTE, historial_eventos),
        Opcion("Seguimiento temporal de un envío", NIVEL_CLIENTE, seguimiento_envio),
        Opcion("Recorrido GPS de un contenedor", NIVEL_OPERADOR, recorrido_contenedor),
        Opcion("Historial de movimientos de un contenedor", NIVEL_OPERADOR, movimientos_contenedor),
        Opcion("Registrar incidente", NIVEL_OPERADOR, registrar_incidente),
        Opcion("Cerrar incidente", NIVEL_OPERADOR, cerrar_incidente),
        Opcion("Incidentes abiertos", NIVEL_CLIENTE, incidentes_abiertos),
        Opcion("Alertas abiertas", NIVEL_OPERADOR, alertas_abiertas),
        Opcion("Cerrar alerta", NIVEL_OPERADOR, cerrar_alerta),
    ]),
    Opcion("Comunicación", NIVEL_CLIENTE, [
        Opcion("Enviar mensaje privado", NIVEL_CLIENTE, enviar_privado),
        Opcion("Ver grupos", NIVEL_CLIENTE, ver_grupos),
        Opcion("Crear grupo", NIVEL_CLIENTE, crear_grupo),
        Opcion("Unirse a un grupo público", NIVEL_CLIENTE, unirse_a_grupo),
        Opcion("Enviar mensaje a un grupo", NIVEL_CLIENTE, enviar_grupal),
        Opcion("Mis conversaciones", NIVEL_CLIENTE, mis_conversaciones),
        Opcion("Historial de una conversación", NIVEL_CLIENTE, historial_conversacion),
        Opcion("Monitor de alertas en tiempo real", NIVEL_OPERADOR, monitor_de_alertas),
    ]),
    Opcion("Gestión comercial y reportes", NIVEL_CLIENTE, [
        Opcion("Solicitar reporte", NIVEL_CLIENTE, solicitar_reporte),
        Opcion("Estado de cuenta corriente", NIVEL_CLIENTE, estado_de_cuenta),
        Opcion("Registrar pago", NIVEL_OPERADOR, registrar_pago),
    ]),
    Opcion("Consultas avanzadas y predicción", NIVEL_CLIENTE, [
        Opcion("Ruta completa de un envío (Neo4j)", NIVEL_CLIENTE, ruta_completa),
        Opcion("Red de relaciones clientes-operadores-envíos (Neo4j)", NIVEL_OPERADOR, red_de_relaciones),
        Opcion("Impacto de una ubicación (Neo4j)", NIVEL_OPERADOR, impacto_de_ubicacion),
        Opcion("Predicciones de atraso del día", NIVEL_OPERADOR, predicciones_del_dia),
        Opcion("Predicciones de un envío", NIVEL_CLIENTE, predicciones_de_envio),
    ]),
    Opcion("Procesos periódicos", NIVEL_ADMIN, [
        Opcion("Facturación de un período", NIVEL_ADMIN, facturar_periodo),
        Opcion("Cierre mensual de cuentas corrientes", NIVEL_ADMIN, cierre_mensual),
        Opcion("Detección de sensores inactivos", NIVEL_ADMIN, detectar_sensores_inactivos),
        Opcion("Predicción diaria de riesgos", NIVEL_ADMIN, prediccion_diaria),
        Opcion("Reconciliar sesiones", NIVEL_ADMIN, reconciliar_sesiones),
        Opcion("Resincronizar grafo", NIVEL_ADMIN, resincronizar_grafo),
        Opcion("Control de integridad", NIVEL_ADMIN, control_de_integridad),
    ]),
]


def ejecutar(app: Aplicacion, sesion: SesionActiva, accion: Accion) -> SesionActiva:
    try:
        sesion = app.auth.sesion_vigente(sesion.id)
    except NoAutorizado as error:
        raise SesionTerminada(str(error)) from error
    try:
        accion(app, sesion)
    except KeyboardInterrupt:
        print("\n  Operación cancelada.")
    except ErrorAplicacion as error:
        print(f"  {type(error).__name__}: {error}")
    except Exception:
        log.exception("Error técnico en %s", accion.__name__)
        print("  Ocurrió un error técnico. El detalle quedó en el log (logistica.log).")
    input("\n  Enter para continuar...")
    return sesion


def mostrar_menu(app: Aplicacion, sesion: SesionActiva, nombre: str, opciones: list[Opcion]) -> None:
    while True:
        visibles = [opcion for opcion in opciones if sesion.nivel >= opcion.nivel]
        titulo(f"{nombre} — {sesion.nombre} ({', '.join(sesion.roles)})")
        for numero, opcion in enumerate(visibles, start=1):
            print(f"  {numero:>2}. {opcion.texto}")
        print("   0. " + ("Cerrar sesión" if opciones is MENU else "Volver"))
        eleccion = input("  Opción: ").strip()
        if eleccion == "0":
            return
        if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(visibles):
            continue
        elegida = visibles[int(eleccion) - 1]
        if isinstance(elegida.destino, list):
            mostrar_menu(app, sesion, elegida.texto, elegida.destino)
        else:
            sesion = ejecutar(app, sesion, elegida.destino)


def crear_administrador_inicial(app: Aplicacion) -> None:
    titulo("No hay usuarios: creá el administrador inicial")
    usuario_id = app.auth.crear_administrador_inicial(pedir_texto("Nombre"), pedir_texto("Apellido"),
                                                      pedir_texto("Email"), pedir_password())
    ok(f"administrador {usuario_id} creado")


def ingresar(app: Aplicacion) -> SesionActiva | None:
    titulo("Plataforma de logística internacional")
    if not app.auth.hay_usuarios():
        crear_administrador_inicial(app)
    print("  1. Ingresar\n  0. Salir")
    if input("  Opción: ").strip() != "1":
        return None
    return app.auth.login(pedir_texto("Email").removeprefix("mailto:"), leer_secreto("  Contraseña: "))


def sesion_de_trabajo(app: Aplicacion, sesion: SesionActiva) -> None:
    try:
        mostrar_menu(app, sesion, "Menú principal", MENU)
        app.auth.logout(sesion)
        print("  Sesión cerrada.")
    except SesionTerminada as motivo:
        print(f"  {motivo}")


def main() -> None:
    app = crear_aplicacion()
    try:
        while True:
            try:
                sesion = ingresar(app)
                if sesion is None:
                    return
                sesion_de_trabajo(app, sesion)
            except KeyboardInterrupt:
                print("\n  Hasta luego.")
                return
            except ErrorAplicacion as error:
                print(f"  {type(error).__name__}: {error}")
            except Exception:
                log.exception("Error técnico en el ingreso")
                print("  Ocurrió un error técnico (¿están levantadas las bases?). Detalle en logistica.log.")
    finally:
        app.cerrar()


if __name__ == "__main__":
    main()
