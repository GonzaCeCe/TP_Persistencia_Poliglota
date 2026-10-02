import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.dominio import reglas
from app.infra.errores import ErrorNegocio
from app.repositorios.documental import RepositorioDocumental
from app.repositorios.grafo import RepositorioGrafo
from app.servicios.auth import SesionActiva

log = logging.getLogger(__name__)

FORMATOS = ("JSON", "CSV")


@dataclass(frozen=True)
class TipoDeReporte:
    descripcion: str
    motor: str
    columnas: tuple[str, ...]
    calcular: Callable[[datetime | None, datetime | None, int | None], list[dict]]


class ServicioReportes:
    def __init__(self, documental: RepositorioDocumental, grafo: RepositorioGrafo, directorio_salidas: Path):
        self._doc = documental
        self._grafo = grafo
        self._salidas = directorio_salidas
        self.tipos = self._catalogo()

    def _catalogo(self) -> dict[str, TipoDeReporte]:
        doc = self._doc
        return {
            "envios_por_pais": TipoDeReporte(
                "Envíos por país de destino", "MongoDB", ("pais", "cantidad"),
                lambda d, h, c: doc.envios_agrupados("pais", d, h, c)),
            "envios_por_estado": TipoDeReporte(
                "Envíos por estado", "MongoDB", ("estado", "cantidad"),
                lambda d, h, c: doc.envios_agrupados("estado", d, h, c)),
            "envios_por_cliente": TipoDeReporte(
                "Envíos por cliente", "MongoDB", ("cliente_id", "cliente", "cantidad"),
                lambda d, h, c: doc.envios_agrupados("cliente", d, h, c)),
            "envios_demorados": TipoDeReporte(
                "Envíos demorados", "MongoDB",
                ("envio_id", "cliente", "estado", "fecha_entrega_estimada", "fecha_entrega_real", "dias_de_demora"),
                lambda d, h, c: doc.envios_demorados(reglas.ahora_utc(), d, h, c)),
            "incidentes_abiertos": TipoDeReporte(
                "Incidentes abiertos", "MongoDB",
                ("_id", "envio_id", "tramo_id", "ruta", "tipo", "severidad", "fecha", "descripcion"),
                lambda d, h, c: doc.incidentes_abiertos(d, h, self._envios_del_cliente(c))),
            "tiempos_por_cliente": TipoDeReporte(
                "Tiempos máximo, mínimo y promedio de envío por cliente (días)", "MongoDB",
                ("cliente_id", "cliente", "entregados", "dias_maximo", "dias_minimo", "dias_promedio"),
                doc.tiempos_de_envio_por_cliente),
            "tiempo_promedio_entrega": TipoDeReporte(
                "Tiempo promedio de entrega (días)", "MongoDB", ("entregados", "dias_promedio"),
                doc.tiempo_promedio_de_entrega),
            "incidentes_por_pais": TipoDeReporte(
                "Promedio de incidentes por envío según país de destino", "MongoDB",
                ("pais", "envios", "incidentes", "promedio"),
                lambda d, h, c: doc.promedio_de_incidentes("pais", d, h, c)),
            "incidentes_por_estado": TipoDeReporte(
                "Promedio de incidentes por envío según estado", "MongoDB",
                ("estado", "envios", "incidentes", "promedio"),
                lambda d, h, c: doc.promedio_de_incidentes("estado", d, h, c)),
            "incidentes_por_cliente": TipoDeReporte(
                "Promedio de incidentes por envío según cliente", "MongoDB",
                ("cliente_id", "cliente", "envios", "incidentes", "promedio"),
                lambda d, h, c: doc.promedio_de_incidentes("cliente", d, h, c)),
            "costos_por_transporte": TipoDeReporte(
                "Costos por tipo de transporte", "MongoDB", ("medio", "tramos", "costo_total", "costo_promedio"),
                doc.costos_por_transporte),
            "ranking_rutas_incidentes": TipoDeReporte(
                "Ranking de rutas con más incidentes", "MongoDB", ("ruta", "incidentes", "abiertos"),
                lambda d, h, c: doc.ranking_rutas_por_incidentes(d, h, self._envios_del_cliente(c))),
            "ranking_clientes_volumen": TipoDeReporte(
                "Ranking de clientes por volumen transportado", "MongoDB",
                ("cliente_id", "cliente", "envios", "volumen_m3", "peso_kg"),
                doc.ranking_clientes_por_volumen),
            "desempeno_historico": TipoDeReporte(
                "Análisis histórico de desempeño: entregas a tiempo por mes", "MongoDB",
                ("mes", "entregados", "a_tiempo", "porcentaje_a_tiempo"),
                doc.desempeno_mensual),
            "red_relaciones": TipoDeReporte(
                "Red de relaciones clientes-operadores-envíos", "Neo4j",
                ("cliente_id", "cliente", "operador_id", "operador", "envios"),
                lambda d, h, c: self._grafo.red_clientes_operadores(c)),
        }

    def _envios_del_cliente(self, cliente_id: int | None) -> list[int] | None:
        return None if cliente_id is None else self._doc.envio_ids_de_cliente(cliente_id)

    def solicitar_reporte(self, sesion: SesionActiva, tipo: str, desde: datetime | None, hasta: datetime | None,
                          formato: str) -> dict:
        if tipo not in self.tipos:
            raise ErrorNegocio(f"Tipo de reporte desconocido: {tipo}")
        if formato not in FORMATOS:
            raise ErrorNegocio(f"Formato inválido: {formato}")
        if desde is not None and hasta is not None and desde >= hasta:
            raise ErrorNegocio("La fecha desde debe ser anterior a la fecha hasta")
        reporte_id = self._doc.siguiente_id("reportes")
        self._doc.insertar_reporte({
            "_id": reporte_id, "usuario_id": sesion.usuario_id, "tipo": tipo,
            "parametros": {"desde": desde, "hasta": hasta, "cliente_id": sesion.cliente_id},
            "formato": formato, "fecha_generacion": reglas.ahora_utc(), "estado": "PENDIENTE", "resultado": None,
        })
        try:
            definicion = self.tipos[tipo]
            filas = [{columna: fila.get(columna) for columna in definicion.columnas}
                     for fila in definicion.calcular(desde, hasta, sesion.cliente_id)]
            archivo = self._exportar(reporte_id, tipo, definicion.columnas, filas, formato)
        except Exception:
            self._doc.finalizar_reporte(reporte_id, "ERROR", None)
            log.exception("Error al generar el reporte %s (%s)", reporte_id, tipo)
            raise
        self._doc.finalizar_reporte(reporte_id, "GENERADO", filas)
        log.info("Reporte %s (%s) generado por el usuario %s: %s filas", reporte_id, tipo, sesion.usuario_id, len(filas))
        return {"reporte_id": reporte_id, "columnas": definicion.columnas, "filas": filas, "archivo": archivo}

    def _exportar(self, reporte_id: int, tipo: str, columnas: tuple[str, ...], filas: list[dict],
                  formato: str) -> Path:
        self._salidas.mkdir(exist_ok=True)
        archivo = self._salidas / f"reporte_{reporte_id}_{tipo}.{formato.lower()}"
        if formato == "JSON":
            archivo.write_text(json.dumps(filas, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
            return archivo
        with archivo.open("w", newline="", encoding="utf-8-sig") as salida:
            escritor = csv.DictWriter(salida, fieldnames=columnas)
            escritor.writeheader()
            for fila in filas:
                escritor.writerow({c: ", ".join(map(str, v)) if isinstance(v, list) else v for c, v in fila.items()})
        return archivo
