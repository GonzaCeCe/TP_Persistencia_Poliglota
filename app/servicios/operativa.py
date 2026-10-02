import logging
from datetime import datetime
from decimal import Decimal

from app.dominio import reglas
from app.infra.errores import ErrorNegocio, NoEncontrado
from app.repositorios.documental import RepositorioDocumental
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import NIVEL_OPERADOR, SesionActiva, requerir_nivel, verificar_acceso_a_envio
from app.servicios.sincronizacion import ServicioSincronizacion

log = logging.getLogger(__name__)

ESTADOS_MANUALES_DE_CONTENEDOR = ("DISPONIBLE", "MANTENIMIENTO", "BAJA")
ESTADOS_DE_SENSOR = ("ACTIVO", "INACTIVO", "FALLA", "BAJA")
PRIORIDADES = ("BAJA", "MEDIA", "ALTA")


class ServicioOperativa:
    def __init__(self, relacional: RepositorioRelacional, documental: RepositorioDocumental,
                 sincronizacion: ServicioSincronizacion):
        self._rel = relacional
        self._doc = documental
        self._sync = sincronizacion

    # Clientes

    def alta_cliente(self, sesion: SesionActiva, razon_social: str, cuit: str, email: str,
                     telefono: str | None, direccion: str | None, pais: str) -> int:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        with self._rel.transaccion():
            cliente_id = self._rel.insertar_cliente(razon_social.strip(), cuit.strip(), email.strip().lower(),
                                                    telefono, direccion, pais.strip().upper())
            self._rel.crear_cuenta(cliente_id=cliente_id)
        log.info("Alta de cliente %s (%s) por el usuario %s", cliente_id, razon_social, sesion.usuario_id)
        self._sync.proyectar_cliente(cliente_id)
        return cliente_id

    def modificar_cliente(self, sesion: SesionActiva, cliente_id: int, campos: dict) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if campos.get("estado") == "BAJA":
            raise ErrorNegocio("Para dar de baja un cliente usá la opción de baja")
        if campos:
            self._rel.actualizar_cliente(cliente_id, campos)
            log.info("Modificación del cliente %s: %s", cliente_id, sorted(campos))
            self._sync.proyectar_cliente(cliente_id)

    def baja_cliente(self, sesion: SesionActiva, cliente_id: int) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        activos = self._doc.contar_envios_activos_de_cliente(cliente_id)
        if activos:
            raise ErrorNegocio(f"El cliente tiene {activos} envíos activos y no se puede dar de baja")
        self._rel.actualizar_cliente(cliente_id, {"estado": "BAJA"})
        log.info("Baja lógica del cliente %s por el usuario %s", cliente_id, sesion.usuario_id)

    def listar_clientes(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._rel.listar_clientes()

    def ver_cliente(self, sesion: SesionActiva, cliente_id: int) -> dict:
        if sesion.cliente_id is not None and sesion.cliente_id != cliente_id:
            requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._rel.obtener_cliente(cliente_id)

    # Empresas (operadores logísticos y proveedores)

    def alta_empresa(self, sesion: SesionActiva, tipo: str, razon_social: str, cuit: str, pais: str) -> int:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        with self._rel.transaccion():
            empresa_id = self._rel.insertar_empresa(tipo, razon_social.strip(), cuit.strip(), pais.strip().upper())
            self._rel.crear_cuenta(empresa_id=empresa_id)
        log.info("Alta de empresa %s %s (%s)", tipo, empresa_id, razon_social)
        return empresa_id

    def modificar_empresa(self, sesion: SesionActiva, empresa_id: int, campos: dict) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if campos.get("estado") == "BAJA":
            raise ErrorNegocio("Para dar de baja una empresa usá la opción de baja")
        if campos:
            self._rel.actualizar_empresa(empresa_id, campos)
            log.info("Modificación de la empresa %s: %s", empresa_id, sorted(campos))

    def baja_empresa(self, sesion: SesionActiva, empresa_id: int) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        self._rel.actualizar_empresa(empresa_id, {"estado": "BAJA"})
        log.info("Baja lógica de la empresa %s por el usuario %s", empresa_id, sesion.usuario_id)

    def listar_empresas(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._rel.listar_empresas()

    # Contenedores, sensores y vehículos

    def alta_contenedor(self, sesion: SesionActiva, codigo: str, tipo: str, capacidad_m3: Decimal,
                        temp_min: Decimal, temp_max: Decimal) -> int:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        contenedor_id = self._rel.insertar_contenedor(codigo.strip().upper(), tipo, capacidad_m3, temp_min, temp_max)
        log.info("Alta de contenedor %s (%s)", contenedor_id, codigo)
        return contenedor_id

    def listar_contenedores(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._rel.listar_contenedores()

    def cambiar_estado_contenedor(self, sesion: SesionActiva, contenedor_id: int, estado: str) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if estado not in ESTADOS_MANUALES_DE_CONTENEDOR:
            raise ErrorNegocio("EN_USO lo asigna el registro de envíos; elegí DISPONIBLE, MANTENIMIENTO o BAJA")
        with self._rel.transaccion():
            bloqueados = self._rel.bloquear_contenedores([contenedor_id])
            if not bloqueados:
                raise NoEncontrado(f"Contenedor {contenedor_id} no existe")
            if bloqueados[0]["estado"] == "EN_USO":
                raise ErrorNegocio("El contenedor está en uso: se libera cuando se entrega o cancela el envío")
            self._rel.cambiar_estado_contenedores([contenedor_id], estado)
        log.info("Contenedor %s pasó a %s", contenedor_id, estado)

    def alta_sensor(self, sesion: SesionActiva, tipo: str, fabricante: str, contenedor_id: int | None = None,
                    fecha_instalacion: datetime | None = None) -> int:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if contenedor_id is not None:
            self._contenedor_utilizable(contenedor_id)
        sensor_id = self._rel.insertar_sensor(tipo, fabricante.strip(), fecha_instalacion or reglas.ahora_utc(),
                                              contenedor_id)
        log.info("Alta de sensor %s (%s) en contenedor %s", sensor_id, tipo, contenedor_id)
        return sensor_id

    def asociar_sensor(self, sesion: SesionActiva, sensor_id: int, contenedor_id: int) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if self._rel.obtener_sensor(sensor_id)["estado"] == "BAJA":
            raise ErrorNegocio(f"El sensor {sensor_id} está dado de baja")
        self._contenedor_utilizable(contenedor_id)
        self._rel.asociar_sensor(sensor_id, contenedor_id)
        log.info("Sensor %s asociado al contenedor %s", sensor_id, contenedor_id)

    def cambiar_estado_sensor(self, sesion: SesionActiva, sensor_id: int, estado: str) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        if estado not in ESTADOS_DE_SENSOR:
            raise ErrorNegocio(f"Estado de sensor inválido: {estado}")
        self._rel.obtener_sensor(sensor_id)
        self._rel.cambiar_estado_sensor(sensor_id, estado)
        log.info("Sensor %s pasó a %s", sensor_id, estado)

    def _contenedor_utilizable(self, contenedor_id: int) -> dict:
        contenedor = self._rel.obtener_contenedor(contenedor_id)
        if contenedor["estado"] == "BAJA":
            raise ErrorNegocio(f"El contenedor {contenedor['codigo_internacional']} está dado de baja")
        return contenedor

    def alta_vehiculo(self, sesion: SesionActiva, tipo: str, identificacion: str, empresa_id: int) -> int:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        empresa = self._rel.obtener_empresa(empresa_id)
        if empresa["tipo"] != "OPERADOR" or empresa["estado"] != "ACTIVO":
            raise ErrorNegocio("El vehículo debe pertenecer a un operador logístico activo")
        vehiculo_id = self._rel.insertar_vehiculo(tipo, identificacion.strip().upper(), empresa_id)
        log.info("Alta de vehículo %s (%s %s) del operador %s", vehiculo_id, tipo, identificacion, empresa_id)
        return vehiculo_id

    def listar_vehiculos(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        return self._rel.listar_vehiculos()

    # Envíos y tramos

    def registrar_envio(self, sesion: SesionActiva, cliente_id: int, origen: dict, destino: dict, prioridad: str,
                        peso_kg: float, volumen_m3: float, contenedor_ids: list[int],
                        fecha_creacion: datetime | None = None) -> int:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        origen = reglas.crear_ubicacion(**origen)
        destino = reglas.crear_ubicacion(**destino)
        self._validar_datos_de_envio(origen, destino, prioridad, contenedor_ids)
        envio_id = None
        try:
            with self._rel.transaccion():
                cliente = self._cliente_activo_bloqueado(cliente_id)
                contenedores = self._reservar_contenedores(sorted(set(contenedor_ids)))
                reglas.validar_carga(peso_kg, volumen_m3, [c["capacidad_m3"] for c in contenedores])
                envio_id = self._doc.siguiente_id("envios")
                self._doc.insertar_envio(_nuevo_envio(envio_id, cliente, origen, destino, prioridad, peso_kg,
                                                      volumen_m3, contenedores,
                                                      fecha_creacion or reglas.ahora_utc()))
        except Exception:
            if envio_id is not None:
                self._doc.borrar_envio(envio_id)
                log.warning("Registro del envío %s revertido: se borró el documento en MongoDB", envio_id)
            raise
        log.info("Envío %s registrado para el cliente %s con contenedores %s", envio_id, cliente_id, contenedor_ids)
        self._sync.proyectar_envio(envio_id)
        return envio_id

    def _validar_datos_de_envio(self, origen: dict, destino: dict, prioridad: str, contenedor_ids: list[int]) -> None:
        if origen["codigo"] == destino["codigo"]:
            raise ErrorNegocio("El origen y el destino deben ser distintos")
        if prioridad not in PRIORIDADES:
            raise ErrorNegocio(f"Prioridad inválida: {prioridad}")
        if not contenedor_ids:
            raise ErrorNegocio("El envío necesita al menos un contenedor")

    def _cliente_activo_bloqueado(self, cliente_id: int) -> dict:
        cliente = self._rel.obtener_cliente(cliente_id, bloquear=True)
        if cliente["estado"] != "ACTIVO":
            raise ErrorNegocio(f"El cliente {cliente['razon_social']} está {cliente['estado']}")
        return cliente

    def _reservar_contenedores(self, contenedor_ids: list[int]) -> list[dict]:
        contenedores = self._rel.bloquear_contenedores(contenedor_ids)
        faltantes = set(contenedor_ids) - {c["id"] for c in contenedores}
        if faltantes:
            raise NoEncontrado(f"Contenedores inexistentes: {sorted(faltantes)}")
        ocupados = [f"{c['codigo_internacional']} ({c['estado']})" for c in contenedores if c["estado"] != "DISPONIBLE"]
        if ocupados:
            raise ErrorNegocio(f"Contenedores no disponibles: {', '.join(ocupados)}")
        self._rel.cambiar_estado_contenedores(contenedor_ids, "EN_USO")
        return contenedores

    def agregar_tramo(self, sesion: SesionActiva, envio_id: int, medio: str, origen: dict, destino: dict,
                      vehiculo_id: int, fecha_salida: datetime, fecha_llegada_estimada: datetime,
                      costo: Decimal) -> str:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        envio = self._doc.obtener_envio(envio_id)
        if not reglas.envio_activo(envio["estado"]):
            raise ErrorNegocio(f"El envío está {envio['estado']} y no admite tramos")
        origen = reglas.crear_ubicacion(**origen)
        destino = reglas.crear_ubicacion(**destino)
        vehiculo = self._vehiculo_operable(vehiculo_id)
        reglas.validar_tramo(medio, vehiculo["tipo"], fecha_salida, fecha_llegada_estimada,
                             reglas.origen_esperado_del_tramo(envio["origen"]["codigo"], envio["tramos"]),
                             origen["codigo"])
        if fecha_salida < envio["fecha_creacion"]:
            raise ErrorNegocio("La salida no puede ser anterior a la creación del envío")
        if costo < 0:
            raise ErrorNegocio("El costo no puede ser negativo")
        tramo = _nuevo_tramo(envio, medio, origen, destino, vehiculo, fecha_salida, fecha_llegada_estimada, costo)
        entrega_estimada = reglas.fecha_entrega_estimada([*envio["tramos"], tramo])
        if not self._doc.agregar_tramo(envio_id, tramo, len(envio["tramos"]), entrega_estimada):
            raise ErrorNegocio("El envío fue modificado por otra operación al mismo tiempo; volvé a intentar")
        log.info("Tramo %s agregado al envío %s (%s, vehículo %s)", tramo["id"], envio_id, medio, vehiculo_id)
        self._sync.proyectar_envio(envio_id)
        return tramo["id"]

    def _vehiculo_operable(self, vehiculo_id: int) -> dict:
        vehiculo = self._rel.obtener_vehiculo(vehiculo_id)
        if vehiculo["estado"] != "ACTIVO":
            raise ErrorNegocio(f"El vehículo {vehiculo['identificacion']} está {vehiculo['estado']}")
        if vehiculo["tipo_empresa"] != "OPERADOR" or vehiculo["estado_empresa"] != "ACTIVO":
            raise ErrorNegocio(f"El operador {vehiculo['razon_social']} no está activo")
        return vehiculo

    def cancelar_envio(self, sesion: SesionActiva, envio_id: int) -> None:
        requerir_nivel(sesion, NIVEL_OPERADOR)
        envio = self._doc.obtener_envio(envio_id)
        if not self._doc.cancelar_envio(envio_id):
            raise ErrorNegocio(f"Solo se cancelan envíos en estado CREADO (está {envio['estado']})")
        self._rel.cambiar_estado_contenedores([c["id"] for c in envio["contenedores"]], "DISPONIBLE", "EN_USO")
        log.info("Envío %s cancelado por el usuario %s; contenedores liberados", envio_id, sesion.usuario_id)
        self._sync.proyectar_envio(envio_id)

    def listar_envios(self, sesion: SesionActiva) -> list[dict]:
        return self._doc.listar_envios(sesion.cliente_id)

    def ver_envio(self, sesion: SesionActiva, envio_id: int) -> dict:
        envio = self._doc.obtener_envio(envio_id)
        verificar_acceso_a_envio(sesion, envio)
        return envio


def _nuevo_envio(envio_id: int, cliente: dict, origen: dict, destino: dict, prioridad: str, peso_kg: float,
                 volumen_m3: float, contenedores: list[dict], fecha_creacion: datetime) -> dict:
    return {
        "_id": envio_id,
        "cliente": {"id": cliente["id"], "razon_social": cliente["razon_social"], "pais": cliente["pais"]},
        "fecha_creacion": fecha_creacion,
        "origen": origen,
        "destino": destino,
        "estado": "CREADO",
        "prioridad": prioridad,
        "peso_kg": float(peso_kg),
        "volumen_m3": float(volumen_m3),
        "contenedores": [{"id": c["id"], "codigo": c["codigo_internacional"]} for c in contenedores],
        "tramos": [],
        "fecha_entrega_estimada": None,
        "fecha_entrega_real": None,
        "cantidad_incidentes": 0,
        "ultimo_evento": None,
        "facturado": False,
        "factura_id": None,
        "grafo_sincronizado": False,
    }


def _nuevo_tramo(envio: dict, medio: str, origen: dict, destino: dict, vehiculo: dict, fecha_salida: datetime,
                 fecha_llegada_estimada: datetime, costo: Decimal) -> dict:
    orden = len(envio["tramos"]) + 1
    return {
        "id": f"{envio['_id']}-{orden}",
        "orden": orden,
        "medio": medio,
        "origen": origen,
        "destino": destino,
        "operador": {"id": vehiculo["empresa_id"], "razon_social": vehiculo["razon_social"]},
        "vehiculo": {"id": vehiculo["id"], "identificacion": vehiculo["identificacion"]},
        "fecha_salida": fecha_salida,
        "fecha_llegada_estimada": fecha_llegada_estimada,
        "costo": float(costo),
    }
