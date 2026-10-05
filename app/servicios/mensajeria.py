import logging
import re
from datetime import datetime

from app.dominio import reglas
from app.infra.errores import ErrorNegocio, NoAutorizado
from app.repositorios.documental import RepositorioDocumental
from app.repositorios.relacional import RepositorioRelacional
from app.servicios.auth import SesionActiva

log = logging.getLogger(__name__)

PATRON_PRIVADA = re.compile(r"^u(\d+)-u(\d+)$")
PATRON_GRUPAL = re.compile(r"^g(\d+)$")


def _es_integrante(grupo: dict, usuario_id: int) -> bool:
    return any(integrante["usuario_id"] == usuario_id for integrante in grupo["integrantes"])


class ServicioMensajeria:
    def __init__(self, relacional: RepositorioRelacional, documental: RepositorioDocumental):
        self._rel = relacional
        self._doc = documental

    def enviar_privado(self, sesion: SesionActiva, destinatario_id: int, contenido: str,
                       fecha_hora: datetime | None = None) -> str:
        conversacion_id = reglas.id_conversacion_privada(sesion.usuario_id, destinatario_id)
        if self._rel.obtener_usuario(destinatario_id)["estado"] != "ACTIVO":
            raise ErrorNegocio(f"El usuario {destinatario_id} no está activo")
        self._doc.insertar_mensaje({
            "conversacion_id": conversacion_id,
            "tipo": "PRIVADO",
            "remitente_id": sesion.usuario_id,
            "destinatario": {"tipo": "USUARIO", "id": destinatario_id},
            "participantes": sorted((sesion.usuario_id, destinatario_id)),
            "fecha_hora": fecha_hora or reglas.ahora_utc(),
            "contenido": reglas.validar_contenido_mensaje(contenido),
        })
        return conversacion_id

    def crear_grupo(self, sesion: SesionActiva, nombre: str, publico: bool, integrante_ids: list[int]) -> int:
        integrantes = sorted(set(integrante_ids) | {sesion.usuario_id})
        if len(integrantes) < 2:
            raise ErrorNegocio("Un grupo necesita al menos 2 integrantes")
        if not nombre.strip():
            raise ErrorNegocio("El grupo necesita un nombre")
        for usuario_id in integrantes:
            self._rel.obtener_usuario(usuario_id)
        grupo_id = self._doc.siguiente_id("grupos")
        self._doc.insertar_grupo({"_id": grupo_id, "nombre": nombre.strip(), "publico": publico,
                                  "integrantes": [{"usuario_id": usuario_id} for usuario_id in integrantes]})
        log.info("Grupo %s (%s, %s) creado por el usuario %s", grupo_id, nombre,
                 "público" if publico else "privado", sesion.usuario_id)
        return grupo_id

    def unirse_a_grupo(self, sesion: SesionActiva, grupo_id: int) -> None:
        if not self._doc.obtener_grupo(grupo_id)["publico"]:
            raise NoAutorizado("Solo podés unirte a grupos públicos")
        if not self._doc.agregar_integrante(grupo_id, sesion.usuario_id):
            raise ErrorNegocio("Ya sos integrante del grupo")

    def enviar_grupal(self, sesion: SesionActiva, grupo_id: int, contenido: str,
                      fecha_hora: datetime | None = None) -> str:
        if not _es_integrante(self._doc.obtener_grupo(grupo_id), sesion.usuario_id):
            raise NoAutorizado("Solo los integrantes pueden escribir en el grupo")
        conversacion_id = reglas.id_conversacion_grupal(grupo_id)
        self._doc.insertar_mensaje({
            "conversacion_id": conversacion_id,
            "tipo": "GRUPAL",
            "remitente_id": sesion.usuario_id,
            "destinatario": {"tipo": "GRUPO", "id": grupo_id},
            "fecha_hora": fecha_hora or reglas.ahora_utc(),
            "contenido": reglas.validar_contenido_mensaje(contenido),
        })
        return conversacion_id

    def grupos(self, sesion: SesionActiva) -> dict:
        return {"mis_grupos": self._doc.grupos_de_usuario(sesion.usuario_id),
                "publicos": self._doc.grupos_publicos()}

    def mis_conversaciones(self, sesion: SesionActiva) -> list[dict]:
        conversaciones = []
        for resumen in self._doc.resumen_conversaciones_privadas(sesion.usuario_id):
            otro_id = next(p for p in resumen["participantes"] if p != sesion.usuario_id)
            otro = self._rel.obtener_usuario(otro_id)
            conversaciones.append(_resumen(resumen, f"Privada con {otro['nombre']} {otro['apellido']} (#{otro_id})"))
        mis_grupos = {reglas.id_conversacion_grupal(g["_id"]): g for g in self._doc.grupos_de_usuario(sesion.usuario_id)}
        for resumen in self._doc.resumen_conversaciones(list(mis_grupos)):
            conversaciones.append(_resumen(resumen, f"Grupo {mis_grupos[resumen['_id']]['nombre']}"))
        return sorted(conversaciones, key=lambda c: c["ultimo_mensaje"], reverse=True)

    def historial_conversacion(self, sesion: SesionActiva, conversacion_id: str) -> list[dict]:
        self._verificar_acceso(sesion, conversacion_id.strip())
        return self._doc.mensajes_de_conversacion(conversacion_id.strip())

    def _verificar_acceso(self, sesion: SesionActiva, conversacion_id: str) -> None:
        privada = PATRON_PRIVADA.match(conversacion_id)
        grupal = PATRON_GRUPAL.match(conversacion_id)
        if privada:
            if sesion.usuario_id not in (int(privada.group(1)), int(privada.group(2))):
                raise NoAutorizado("No participás de esa conversación")
        elif grupal:
            grupo = self._doc.obtener_grupo(int(grupal.group(1)))
            if not grupo["publico"] and not _es_integrante(grupo, sesion.usuario_id):
                raise NoAutorizado("El grupo es privado y no sos integrante")
        else:
            raise ErrorNegocio("Identificador de conversación inválido (formato u1-u2 o g1)")


def _resumen(resumen: dict, titulo: str) -> dict:
    return {"conversacion_id": resumen["_id"], "titulo": titulo, "mensajes": resumen["mensajes"],
            "ultimo_mensaje": resumen["fecha_hora"], "ultimo_contenido": resumen["contenido"]}
