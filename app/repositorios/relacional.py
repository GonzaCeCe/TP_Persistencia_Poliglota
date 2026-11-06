from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator
from uuid import UUID

import psycopg
from psycopg import sql

from app.infra.conexiones import Conexiones
from app.infra.errores import IntegridadError, NoEncontrado

MENSAJES_DE_RESTRICCION = {
    "cliente_cuit_key": "Ya existe un cliente con ese CUIT",
    "cliente_cuit_check": "El CUIT debe tener el formato NN-NNNNNNNN-N",
    "cliente_email_check": "El email no es válido",
    "cliente_pais_check": "El país debe ser un código de 2 letras mayúsculas",
    "empresa_cuit_key": "Ya existe una empresa con ese CUIT",
    "empresa_cuit_check": "El CUIT debe tener el formato NN-NNNNNNNN-N",
    "empresa_pais_check": "El país debe ser un código de 2 letras mayúsculas",
    "usuario_email_key": "Ya existe un usuario con ese email",
    "usuario_email_check": "El email no es válido",
    "usuario_cliente_id_fkey": "El cliente indicado no existe",
    "contenedor_codigo_internacional_key": "Ya existe un contenedor con ese código",
    "contenedor_codigo_internacional_check": "El código debe tener 4 letras y 7 dígitos (ISO 6346)",
    "contenedor_capacidad_m3_check": "La capacidad debe ser mayor a cero",
    "contenedor_check": "La temperatura mínima debe ser menor que la máxima",
    "sensor_contenedor_id_fkey": "El contenedor indicado no existe",
    "vehiculo_identificacion_key": "Ya existe un vehículo con esa identificación",
    "vehiculo_empresa_id_fkey": "La empresa indicada no existe",
    "factura_item_envio_id_key": "El envío ya tiene un ítem de factura",
    "ux_movimiento_cuenta_envio": "La cuenta ya tiene un movimiento por ese envío",
    "pago_monto_check": "El monto debe ser mayor a cero",
}

COLUMNAS_EDITABLES = {
    "cliente": {"razon_social", "email", "telefono", "direccion", "pais", "estado"},
    "empresa": {"razon_social", "pais", "estado"},
}

SALDO_FIRMADO = "CASE tipo WHEN 'DEBE' THEN importe ELSE -importe END"


@contextmanager
def _traducir_errores() -> Iterator[None]:
    try:
        yield
    except psycopg.IntegrityError as error:
        restriccion = error.diag.constraint_name
        raise IntegridadError(MENSAJES_DE_RESTRICCION.get(
            restriccion, f"Se violó la restricción {restriccion}")) from error
    except psycopg.DataError as error:
        raise IntegridadError(f"Dato inválido: {error.diag.message_primary}") from error


class RepositorioRelacional:
    def __init__(self, conexiones: Conexiones):
        self._conexiones = conexiones

    @contextmanager
    def transaccion(self) -> Iterator[None]:
        with _traducir_errores(), self._conexiones.postgres().transaction():
            yield

    def _ejecutar(self, consulta, parametros=None) -> psycopg.Cursor:
        with _traducir_errores():
            return self._conexiones.postgres().execute(consulta, parametros)

    def _uno(self, consulta, parametros=None) -> dict | None:
        return self._ejecutar(consulta, parametros).fetchone()

    def _todos(self, consulta, parametros=None) -> list[dict]:
        return self._ejecutar(consulta, parametros).fetchall()

    def _uno_obligatorio(self, descripcion: str, consulta, parametros=None) -> dict:
        fila = self._uno(consulta, parametros)
        if fila is None:
            raise NoEncontrado(f"{descripcion} no existe")
        return fila

    def _actualizar(self, tabla: str, id_: int, campos: dict) -> None:
        no_editables = set(campos) - COLUMNAS_EDITABLES[tabla]
        if no_editables:
            raise ValueError(f"Columnas no editables en {tabla}: {no_editables}")
        asignaciones = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(columna), sql.Placeholder()) for columna in campos)
        consulta = sql.SQL("UPDATE {} SET {} WHERE id = %s RETURNING id").format(
            sql.Identifier(tabla), asignaciones)
        self._uno_obligatorio(f"{tabla.capitalize()} {id_}", consulta, [*campos.values(), id_])

    # Clientes

    def insertar_cliente(self, razon_social: str, cuit: str, email: str, telefono: str | None,
                         direccion: str | None, pais: str) -> int:
        return self._uno(
            "INSERT INTO cliente (razon_social, cuit, email, telefono, direccion, pais) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (razon_social, cuit, email, telefono, direccion, pais))["id"]

    def obtener_cliente(self, cliente_id: int) -> dict:
        return self._uno_obligatorio(f"Cliente {cliente_id}", "SELECT * FROM cliente WHERE id = %s", (cliente_id,))

    def listar_clientes(self) -> list[dict]:
        return self._todos("SELECT * FROM cliente ORDER BY id")

    def actualizar_cliente(self, cliente_id: int, campos: dict) -> None:
        self._actualizar("cliente", cliente_id, campos)

    # Empresas

    def insertar_empresa(self, tipo: str, razon_social: str, cuit: str, pais: str) -> int:
        return self._uno(
            "INSERT INTO empresa (tipo, razon_social, cuit, pais) VALUES (%s, %s, %s, %s) RETURNING id",
            (tipo, razon_social, cuit, pais))["id"]

    def obtener_empresa(self, empresa_id: int) -> dict:
        return self._uno_obligatorio(f"Empresa {empresa_id}", "SELECT * FROM empresa WHERE id = %s", (empresa_id,))

    def listar_empresas(self) -> list[dict]:
        return self._todos("SELECT * FROM empresa ORDER BY id")

    def actualizar_empresa(self, empresa_id: int, campos: dict) -> None:
        self._actualizar("empresa", empresa_id, campos)

    # Cuentas corrientes

    def crear_cuenta(self, cliente_id: int | None = None, empresa_id: int | None = None) -> int:
        return self._uno("INSERT INTO cuenta_corriente (cliente_id, empresa_id) VALUES (%s, %s) RETURNING id",
                         (cliente_id, empresa_id))["id"]

    def obtener_cuenta(self, cliente_id: int | None = None, empresa_id: int | None = None) -> dict:
        titular = "cliente_id" if cliente_id is not None else "empresa_id"
        return self._uno_obligatorio(
            "Cuenta corriente",
            sql.SQL("SELECT * FROM cuenta_corriente WHERE {} = %s").format(sql.Identifier(titular)),
            (cliente_id if cliente_id is not None else empresa_id,))

    def bloquear_cuenta_empresa(self, empresa_id: int) -> dict:
        return self._uno_obligatorio(
            f"Cuenta corriente de empresa {empresa_id}",
            "SELECT cc.*, e.tipo AS tipo_empresa FROM cuenta_corriente cc "
            "JOIN empresa e ON e.id = cc.empresa_id "
            "WHERE cc.empresa_id = %s FOR UPDATE OF cc",
            (empresa_id,),
        )

    def listar_cuentas(self) -> list[dict]:
        return self._todos(
            "SELECT cc.*, COALESCE(c.razon_social, e.razon_social) AS titular, "
            "CASE WHEN cc.cliente_id IS NOT NULL THEN 'CLIENTE' ELSE e.tipo END AS tipo_titular "
            "FROM cuenta_corriente cc LEFT JOIN cliente c ON c.id = cc.cliente_id "
            "LEFT JOIN empresa e ON e.id = cc.empresa_id ORDER BY cc.id")

    def registrar_movimiento(self, cuenta_id: int, fecha: date, tipo: str, importe: Decimal, descripcion: str,
                             factura_id: int | None = None, pago_id: int | None = None,
                             envio_id: int | None = None) -> None:
        self._ejecutar(
            "INSERT INTO movimiento_cc (cuenta_id, fecha, tipo, importe, factura_id, pago_id, envio_id, descripcion) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (cuenta_id, fecha, tipo, importe, factura_id, pago_id, envio_id, descripcion))
        variacion = importe if tipo == "DEBE" else -importe
        self._ejecutar("UPDATE cuenta_corriente SET saldo = saldo + %s, fecha_actualizacion = now() WHERE id = %s",
                       (variacion, cuenta_id))

    def movimientos_de_cuenta(self, cuenta_id: int) -> list[dict]:
        return self._todos("SELECT * FROM movimiento_cc WHERE cuenta_id = %s ORDER BY fecha, id", (cuenta_id,))

    def cierres_de_cuenta(self, cuenta_id: int) -> list[dict]:
        return self._todos("SELECT * FROM cierre_cc WHERE cuenta_id = %s ORDER BY periodo", (cuenta_id,))

    def existe_cierre(self, periodo: str) -> bool:
        return self._uno("SELECT EXISTS (SELECT 1 FROM cierre_cc WHERE periodo = %s) AS existe",
                         (periodo,))["existe"]

    def cerrar_periodo(self, periodo: str, periodo_anterior: str, inicio: date, fin: date) -> int:
        return self._ejecutar(
            f"""
            INSERT INTO cierre_cc (cuenta_id, periodo, saldo_inicial, total_debe, total_haber, saldo_final)
            SELECT t.cuenta_id, %(periodo)s, t.inicial, t.debe, t.haber, t.inicial + t.debe - t.haber
            FROM (
                SELECT c.id AS cuenta_id,
                       COALESCE(
                           (SELECT saldo_final FROM cierre_cc WHERE cuenta_id = c.id AND periodo = %(anterior)s),
                           (SELECT COALESCE(SUM({SALDO_FIRMADO}), 0) FROM movimiento_cc
                             WHERE cuenta_id = c.id AND fecha < %(inicio)s)
                       ) AS inicial,
                       (SELECT COALESCE(SUM(CASE WHEN tipo = 'DEBE' THEN importe ELSE 0 END), 0) FROM movimiento_cc
                         WHERE cuenta_id = c.id AND fecha >= %(inicio)s AND fecha < %(fin)s) AS debe,
                       (SELECT COALESCE(SUM(CASE WHEN tipo = 'HABER' THEN importe ELSE 0 END), 0) FROM movimiento_cc
                         WHERE cuenta_id = c.id AND fecha >= %(inicio)s AND fecha < %(fin)s) AS haber
                FROM cuenta_corriente c
            ) t
            """,
            {"periodo": periodo, "anterior": periodo_anterior, "inicio": inicio, "fin": fin}).rowcount

    # Usuarios, roles y sesiones

    def _con_roles(self, usuario: dict | None) -> dict | None:
        if usuario is None:
            return None
        roles = self._todos("SELECT r.descripcion, r.nivel_permisos FROM usuario_rol ur JOIN rol r ON r.id = ur.rol_id "
                            "WHERE ur.usuario_id = %s ORDER BY r.id", (usuario["id"],))
        return {**usuario, "roles": [rol["descripcion"] for rol in roles],
                "nivel": max((rol["nivel_permisos"] for rol in roles), default=0)}

    def insertar_usuario(self, cliente_id: int | None, nombre: str, apellido: str, email: str,
                         password_hash: str, fecha_registro: datetime) -> int:
        return self._uno(
            "INSERT INTO usuario (cliente_id, nombre, apellido, email, password_hash, fecha_registro) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (cliente_id, nombre, apellido, email, password_hash, fecha_registro))["id"]

    def asignar_rol(self, usuario_id: int, rol: str) -> None:
        rol_id = self._uno_obligatorio(f"Rol {rol}", "SELECT id FROM rol WHERE descripcion = %s", (rol,))["id"]
        ya_asignado = self._uno("SELECT 1 AS asignado FROM usuario_rol WHERE usuario_id = %s AND rol_id = %s",
                                (usuario_id, rol_id))
        if ya_asignado is None:
            self._ejecutar("INSERT INTO usuario_rol (usuario_id, rol_id) VALUES (%s, %s)", (usuario_id, rol_id))

    def obtener_usuario(self, usuario_id: int) -> dict:
        return self._con_roles(self._uno_obligatorio(f"Usuario {usuario_id}",
                                                     "SELECT * FROM usuario WHERE id = %s", (usuario_id,)))

    def buscar_usuario_por_email(self, email: str) -> dict | None:
        return self._con_roles(self._uno("SELECT * FROM usuario WHERE email = %s", (email,)))

    def listar_usuarios(self) -> list[dict]:
        return [self._con_roles(usuario) for usuario in self._todos("SELECT * FROM usuario ORDER BY id")]

    def cambiar_estado_usuario(self, usuario_id: int, estado: str) -> None:
        self._uno_obligatorio(f"Usuario {usuario_id}",
                              "UPDATE usuario SET estado = %s WHERE id = %s RETURNING id", (estado, usuario_id))

    def insertar_sesion(self, sesion_id: UUID, usuario_id: int, fecha_inicio: datetime) -> None:
        self._ejecutar("INSERT INTO sesion (id, usuario_id, fecha_inicio, estado) VALUES (%s, %s, %s, 'ACTIVA')",
                       (sesion_id, usuario_id, fecha_inicio))

    def finalizar_sesiones(self, sesion_ids: list[UUID], estado: str, fecha_fin: datetime) -> int:
        return self._ejecutar(
            "UPDATE sesion SET estado = %s, fecha_fin = %s WHERE id = ANY(%s) AND estado = 'ACTIVA'",
            (estado, fecha_fin, sesion_ids)).rowcount

    def finalizar_sesiones_de_usuario(self, usuario_id: int, estado: str, fecha_fin: datetime) -> int:
        return self._ejecutar(
            "UPDATE sesion SET estado = %s, fecha_fin = %s WHERE usuario_id = %s AND estado = 'ACTIVA'",
            (estado, fecha_fin, usuario_id)).rowcount

    def sesiones_activas(self, usuario_id: int | None = None) -> list[dict]:
        if usuario_id is None:
            return self._todos("SELECT * FROM sesion WHERE estado = 'ACTIVA' ORDER BY fecha_inicio")
        return self._todos("SELECT * FROM sesion WHERE estado = 'ACTIVA' AND usuario_id = %s ORDER BY fecha_inicio",
                           (usuario_id,))

    # Contenedores, sensores y vehículos

    def insertar_contenedor(self, codigo: str, tipo: str, capacidad_m3: Decimal,
                            temp_min: Decimal, temp_max: Decimal) -> int:
        return self._uno(
            "INSERT INTO contenedor (codigo_internacional, tipo, capacidad_m3, temp_min, temp_max) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (codigo, tipo, capacidad_m3, temp_min, temp_max))["id"]

    def obtener_contenedor(self, contenedor_id: int) -> dict:
        return self._uno_obligatorio(f"Contenedor {contenedor_id}",
                                     "SELECT * FROM contenedor WHERE id = %s", (contenedor_id,))

    def listar_contenedores(self, contenedor_ids: list[int] | None = None) -> list[dict]:
        if contenedor_ids is None:
            return self._todos("SELECT * FROM contenedor ORDER BY id")
        return self._todos("SELECT * FROM contenedor WHERE id = ANY(%s) ORDER BY id", (contenedor_ids,))

    def bloquear_contenedores(self, contenedor_ids: list[int]) -> list[dict]:
        return self._todos("SELECT * FROM contenedor WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (contenedor_ids,))

    def cambiar_estado_contenedores(self, contenedor_ids: list[int], estado: str,
                                    estado_actual: str | None = None) -> int:
        if estado_actual is None:
            return self._ejecutar("UPDATE contenedor SET estado = %s WHERE id = ANY(%s)",
                                  (estado, contenedor_ids)).rowcount
        return self._ejecutar("UPDATE contenedor SET estado = %s WHERE id = ANY(%s) AND estado = %s",
                              (estado, contenedor_ids, estado_actual)).rowcount

    _SENSOR_CON_CONTENEDOR = (
        "SELECT s.*, c.codigo_internacional, c.temp_min, c.temp_max "
        "FROM sensor s LEFT JOIN contenedor c ON c.id = s.contenedor_id ")

    def insertar_sensor(self, tipo: str, fabricante: str, fecha_instalacion: datetime,
                        contenedor_id: int | None) -> int:
        return self._uno(
            "INSERT INTO sensor (tipo, fabricante, fecha_instalacion, contenedor_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (tipo, fabricante, fecha_instalacion, contenedor_id))["id"]

    def obtener_sensor(self, sensor_id: int) -> dict:
        return self._uno_obligatorio(f"Sensor {sensor_id}",
                                     self._SENSOR_CON_CONTENEDOR + "WHERE s.id = %s", (sensor_id,))

    def listar_sensores(self) -> list[dict]:
        return self._todos(self._SENSOR_CON_CONTENEDOR + "ORDER BY s.id")

    def asociar_sensor(self, sensor_id: int, contenedor_id: int) -> None:
        self._uno_obligatorio(f"Sensor {sensor_id}", "UPDATE sensor SET contenedor_id = %s WHERE id = %s RETURNING id",
                              (contenedor_id, sensor_id))

    def cambiar_estado_sensor(self, sensor_id: int, estado: str, estado_actual: str | None = None) -> bool:
        if estado_actual is None:
            return self._ejecutar("UPDATE sensor SET estado = %s WHERE id = %s", (estado, sensor_id)).rowcount == 1
        return self._ejecutar("UPDATE sensor SET estado = %s WHERE id = %s AND estado = %s",
                              (estado, sensor_id, estado_actual)).rowcount == 1

    def sensores_activos_instalados_antes(self, limite: datetime) -> list[dict]:
        return self._todos(self._SENSOR_CON_CONTENEDOR + "WHERE s.estado = 'ACTIVO' AND s.fecha_instalacion < %s "
                           "ORDER BY s.id", (limite,))

    _VEHICULO_CON_EMPRESA = (
        "SELECT v.*, e.razon_social, e.tipo AS tipo_empresa, e.estado AS estado_empresa "
        "FROM vehiculo v JOIN empresa e ON e.id = v.empresa_id ")

    def insertar_vehiculo(self, tipo: str, identificacion: str, empresa_id: int) -> int:
        return self._uno("INSERT INTO vehiculo (tipo, identificacion, empresa_id) VALUES (%s, %s, %s) RETURNING id",
                         (tipo, identificacion, empresa_id))["id"]

    def obtener_vehiculo(self, vehiculo_id: int) -> dict:
        return self._uno_obligatorio(f"Vehículo {vehiculo_id}",
                                     self._VEHICULO_CON_EMPRESA + "WHERE v.id = %s", (vehiculo_id,))

    def listar_vehiculos(self) -> list[dict]:
        return self._todos(self._VEHICULO_CON_EMPRESA + "ORDER BY v.id")

    # Facturación y pagos

    def facturas_de_envios(self, envio_ids: list[int]) -> dict[int, int]:
        filas = self._todos("SELECT envio_id, factura_id FROM factura_item WHERE envio_id = ANY(%s)", (envio_ids,))
        return {fila["envio_id"]: fila["factura_id"] for fila in filas}

    def insertar_factura(self, cliente_id: int, periodo: str, fecha_emision: date, importe_total: Decimal) -> int:
        return self._uno(
            "INSERT INTO factura (cliente_id, periodo, fecha_emision, importe_total) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (cliente_id, periodo, fecha_emision, importe_total))["id"]

    def insertar_item(self, factura_id: int, envio_id: int, importe: Decimal) -> None:
        self._ejecutar("INSERT INTO factura_item (factura_id, envio_id, importe) VALUES (%s, %s, %s)",
                       (factura_id, envio_id, importe))

    _FACTURA_CON_PAGOS = (
        "SELECT f.*, COALESCE((SELECT SUM(p.monto) FROM pago p WHERE p.factura_id = f.id), 0) AS pagado "
        "FROM factura f ")

    def bloquear_factura(self, factura_id: int) -> dict:
        return self._uno_obligatorio(f"Factura {factura_id}",
                                     self._FACTURA_CON_PAGOS + "WHERE f.id = %s FOR UPDATE", (factura_id,))

    def facturas_de_cliente(self, cliente_id: int) -> list[dict]:
        return self._todos(self._FACTURA_CON_PAGOS + "WHERE f.cliente_id = %s ORDER BY f.fecha_emision, f.id",
                           (cliente_id,))

    def insertar_pago(self, factura_id: int, fecha: date, monto: Decimal, medio_pago: str) -> int:
        return self._uno("INSERT INTO pago (factura_id, fecha, monto, medio_pago) VALUES (%s, %s, %s, %s) RETURNING id",
                         (factura_id, fecha, monto, medio_pago))["id"]

    def actualizar_estado_factura(self, factura_id: int, estado: str) -> None:
        self._ejecutar("UPDATE factura SET estado = %s WHERE id = %s", (estado, factura_id))

    # Control de integridad

    def cuentas_con_saldo_inconsistente(self) -> list[dict]:
        return self._todos(
            f"SELECT c.id AS cuenta_id, c.saldo, COALESCE(SUM({SALDO_FIRMADO}), 0) AS suma_movimientos "
            "FROM cuenta_corriente c LEFT JOIN movimiento_cc m ON m.cuenta_id = c.id "
            f"GROUP BY c.id HAVING c.saldo <> COALESCE(SUM({SALDO_FIRMADO}), 0) ORDER BY c.id")

    def facturas_con_importe_inconsistente(self) -> list[dict]:
        return self._todos(
            "SELECT f.id AS factura_id, f.importe_total, COALESCE(SUM(i.importe), 0) AS suma_items "
            "FROM factura f LEFT JOIN factura_item i ON i.factura_id = f.id "
            "GROUP BY f.id HAVING f.importe_total <> COALESCE(SUM(i.importe), 0) ORDER BY f.id")
