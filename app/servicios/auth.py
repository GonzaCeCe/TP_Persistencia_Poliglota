import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import bcrypt

from app.dominio import reglas
from app.infra.errores import ErrorNegocio, NoAutorizado
from app.repositorios.clave_valor import RepositorioClaveValor
from app.repositorios.relacional import RepositorioRelacional

log = logging.getLogger(__name__)

NIVEL_ADMIN = 5
NIVEL_OPERADOR = 3
NIVEL_CLIENTE = 1
ESTADOS_DE_USUARIO = ("ACTIVO", "BLOQUEADO", "BAJA")


@dataclass(frozen=True)
class SesionActiva:
    id: str
    usuario_id: int
    nombre: str
    nivel: int
    roles: tuple[str, ...]
    cliente_id: int | None


def requerir_nivel(sesion: SesionActiva, nivel: int) -> None:
    if sesion.nivel < nivel:
        raise NoAutorizado("Tu rol no permite esta operación")


def verificar_acceso_a_envio(sesion: SesionActiva, envio: dict) -> None:
    if sesion.cliente_id is not None and envio["cliente"]["id"] != sesion.cliente_id:
        raise NoAutorizado(f"No tenés acceso al envío {envio['_id']}")


def _validar_roles(roles: list[str], cliente_id: int | None) -> None:
    if not roles:
        raise ErrorNegocio("El usuario necesita al menos un rol")
    if "CLIENTE" in roles and cliente_id is None:
        raise ErrorNegocio("Un usuario con rol CLIENTE debe pertenecer a un cliente")
    if cliente_id is not None and set(roles) != {"CLIENTE"}:
        raise ErrorNegocio("Un usuario de cliente solo puede tener el rol CLIENTE")


class ServicioAuth:
    def __init__(self, relacional: RepositorioRelacional, clave_valor: RepositorioClaveValor, ttl_sesion: int):
        self._rel = relacional
        self._kv = clave_valor
        self._ttl_sesion = ttl_sesion

    def hay_usuarios(self) -> bool:
        return bool(self._rel.listar_usuarios())

    def crear_administrador_inicial(self, nombre: str, apellido: str, email: str, password: str) -> int:
        if self.hay_usuarios():
            raise ErrorNegocio("El administrador inicial solo se crea cuando no hay usuarios")
        return self._crear_usuario(None, nombre, apellido, email, password, ["ADMIN"], None)

    def registrar_usuario(self, sesion: SesionActiva, nombre: str, apellido: str, email: str, password: str,
                          roles: list[str], cliente_id: int | None = None,
                          fecha_registro: datetime | None = None) -> int:
        requerir_nivel(sesion, NIVEL_ADMIN)
        return self._crear_usuario(cliente_id, nombre, apellido, email, password, roles, fecha_registro)

    def _crear_usuario(self, cliente_id: int | None, nombre: str, apellido: str, email: str, password: str,
                       roles: list[str], fecha_registro: datetime | None) -> int:
        reglas.validar_password(password)
        _validar_roles(roles, cliente_id)
        if cliente_id is not None and self._rel.obtener_cliente(cliente_id)["estado"] == "BAJA":
            raise ErrorNegocio(f"El cliente {cliente_id} está dado de baja")
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        with self._rel.transaccion():
            usuario_id = self._rel.insertar_usuario(cliente_id, nombre.strip(), apellido.strip(),
                                                    email.strip().lower(), password_hash,
                                                    fecha_registro or reglas.ahora_utc())
            for rol in roles:
                self._rel.asignar_rol(usuario_id, rol)
        log.info("Alta de usuario %s (%s) con roles %s", usuario_id, email, roles)
        return usuario_id

    def asignar_rol(self, sesion: SesionActiva, usuario_id: int, rol: str) -> None:
        requerir_nivel(sesion, NIVEL_ADMIN)
        usuario = self._rel.obtener_usuario(usuario_id)
        _validar_roles([*usuario["roles"], rol], usuario["cliente_id"])
        self._rel.asignar_rol(usuario_id, rol)
        log.info("Rol %s asignado al usuario %s por %s", rol, usuario_id, sesion.usuario_id)

    def cambiar_estado_usuario(self, sesion: SesionActiva, usuario_id: int, estado: str) -> None:
        requerir_nivel(sesion, NIVEL_ADMIN)
        if estado not in ESTADOS_DE_USUARIO:
            raise ErrorNegocio(f"Estado de usuario inválido: {estado}")
        if usuario_id == sesion.usuario_id and estado != "ACTIVO":
            raise ErrorNegocio("No podés bloquear ni dar de baja tu propio usuario")
        self._rel.cambiar_estado_usuario(usuario_id, estado)
        if estado != "ACTIVO":
            self._cerrar_sesiones(usuario_id)
        log.info("Usuario %s pasó a %s por %s", usuario_id, estado, sesion.usuario_id)

    def listar_usuarios(self, sesion: SesionActiva) -> list[dict]:
        requerir_nivel(sesion, NIVEL_ADMIN)
        return self._rel.listar_usuarios()

    def login(self, email: str, password: str) -> SesionActiva:
        email = email.strip().lower()
        usuario = self._rel.buscar_usuario_por_email(email)
        if usuario is None or not bcrypt.checkpw(password.encode(), usuario["password_hash"].encode()):
            log.info("Login fallido para %s", email)
            raise NoAutorizado("Email o contraseña incorrectos")
        if usuario["estado"] != "ACTIVO":
            log.info("Login rechazado para %s: usuario %s", email, usuario["estado"])
            raise NoAutorizado(f"El usuario está {usuario['estado']}")
        if not usuario["roles"]:
            raise NoAutorizado("El usuario no tiene roles asignados")
        sesion = SesionActiva(str(uuid4()), usuario["id"], f"{usuario['nombre']} {usuario['apellido']}",
                              usuario["nivel"], tuple(usuario["roles"]), usuario["cliente_id"])
        self._rel.insertar_sesion(UUID(sesion.id), sesion.usuario_id, reglas.ahora_utc())
        self._kv.crear_sesion(sesion.id, sesion.usuario_id, _a_hash(sesion), self._ttl_sesion)
        log.info("Login del usuario %s (sesión %s)", sesion.usuario_id, sesion.id)
        return sesion

    def sesion_vigente(self, sesion_id: str) -> SesionActiva:
        datos = self._kv.obtener_sesion(sesion_id)
        if datos is None:
            raise NoAutorizado("La sesión expiró. Volvé a ingresar.")
        self._kv.renovar_sesion(sesion_id, self._ttl_sesion)
        return _desde_hash(sesion_id, datos)

    def logout(self, sesion: SesionActiva) -> None:
        self._rel.finalizar_sesiones([UUID(sesion.id)], "CERRADA", reglas.ahora_utc())
        self._kv.borrar_sesiones(sesion.usuario_id, [sesion.id])
        log.info("Logout del usuario %s (sesión %s)", sesion.usuario_id, sesion.id)

    def mis_sesiones(self, sesion: SesionActiva) -> list[dict]:
        en_redis = self._kv.sesiones_de_usuario(sesion.usuario_id)
        vencidas = [sesion_id for sesion_id in en_redis if not self._kv.existe_sesion(sesion_id)]
        self._kv.borrar_sesiones(sesion.usuario_id, vencidas)
        vigentes = en_redis - set(vencidas)
        return [{**fila, "actual": str(fila["id"]) == sesion.id}
                for fila in self._rel.sesiones_activas(sesion.usuario_id) if str(fila["id"]) in vigentes]

    def cerrar_sesiones_de_usuario(self, sesion: SesionActiva, usuario_id: int) -> int:
        if usuario_id != sesion.usuario_id:
            requerir_nivel(sesion, NIVEL_ADMIN)
        self._rel.obtener_usuario(usuario_id)
        cerradas = self._cerrar_sesiones(usuario_id)
        log.info("Se cerraron %s sesiones del usuario %s a pedido de %s", cerradas, usuario_id, sesion.usuario_id)
        return cerradas

    def _cerrar_sesiones(self, usuario_id: int) -> int:
        cerradas = self._rel.finalizar_sesiones_de_usuario(usuario_id, "CERRADA", reglas.ahora_utc())
        self._kv.borrar_sesiones(usuario_id, list(self._kv.sesiones_de_usuario(usuario_id)))
        return cerradas

    def reconciliar_sesiones(self, sesion: SesionActiva) -> int:
        requerir_nivel(sesion, NIVEL_ADMIN)
        sin_clave = [fila["id"] for fila in self._rel.sesiones_activas() if not self._kv.existe_sesion(str(fila["id"]))]
        expiradas = self._rel.finalizar_sesiones(sin_clave, "EXPIRADA", reglas.ahora_utc()) if sin_clave else 0
        log.info("Reconciliación de sesiones: %s marcadas como EXPIRADA", expiradas)
        return expiradas


def _a_hash(sesion: SesionActiva) -> dict[str, str]:
    return {"usuario_id": str(sesion.usuario_id), "nombre": sesion.nombre, "nivel": str(sesion.nivel),
            "roles": ",".join(sesion.roles), "cliente_id": "" if sesion.cliente_id is None else str(sesion.cliente_id)}


def _desde_hash(sesion_id: str, datos: dict[str, str]) -> SesionActiva:
    return SesionActiva(sesion_id, int(datos["usuario_id"]), datos["nombre"], int(datos["nivel"]),
                        tuple(datos["roles"].split(",")), int(datos["cliente_id"]) if datos["cliente_id"] else None)
