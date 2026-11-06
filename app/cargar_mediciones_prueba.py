
import random
from datetime import timedelta

from pymongo import UpdateOne

from app.ensamblado import crear_aplicacion
from app.repositorios.relacional import RepositorioRelacional


COORDENADAS = {
    "ARROS": (-32.95, -60.64),
    "ARBUE": (-34.60, -58.37),
    "ARMDZ": (-32.89, -68.84),
    "BRSSZ": (-23.96, -46.33),
    "USNYC": (40.71, -74.01),
    "ARCOR": (-31.42, -64.19),
    "ARLPG": (-34.92, -57.95),
    "ARBHI": (-38.72, -62.27),
    "ARSFN": (-31.63, -60.70),
    "ARMDQ": (-38.00, -57.55),
    "ARNQN": (-38.95, -68.06),
    "ARSLA": (-24.79, -65.41),
    "ARTUC": (-26.82, -65.22),
}

MEDICIONES_POR_CONTENEDOR = 300
TOTAL_CLIENTES = 10


def seleccionar_sensores(clientes, envios, sensores):
    seleccion = []
    contenedores_usados = set()

    for cliente in clientes:
        candidatos = [
            envio for envio in envios
            if envio["cliente"]["id"] == cliente["id"] and envio.get("contenedores")
        ]
        candidatos.sort(key=lambda envio: envio["_id"])
        encontrado = None

        for envio in candidatos:
            for contenedor in envio["contenedores"]:
                contenedor_id = contenedor["id"]
                disponibles = [
                    sensor for sensor in sensores
                    if sensor["contenedor_id"] == contenedor_id and sensor["estado"] != "BAJA"
                ]
                disponibles.sort(key=lambda sensor: (sensor["tipo"] != "MULTI", sensor["id"]))

                if disponibles and contenedor_id not in contenedores_usados:
                    encontrado = (cliente, envio, contenedor_id, disponibles[0])
                    break

            if encontrado:
                break

        if encontrado is None:
            raise RuntimeError(
                f"Falta un envío con contenedor y sensor para {cliente['razon_social']}"
            )

        seleccion.append(encontrado)
        contenedores_usados.add(encontrado[2])

    if len(seleccion) != TOTAL_CLIENTES:
        raise RuntimeError(
            f"Se esperaban {TOTAL_CLIENTES} clientes, pero se encontraron {len(seleccion)}"
        )

    return seleccion


def construir_lecturas(cliente, envio, contenedor_id, sensor):
    origen = COORDENADAS.get(envio["origen"]["codigo"])
    destino = COORDENADAS.get(envio["destino"]["codigo"])

    if origen is None or destino is None:
        raise RuntimeError(f"Faltan coordenadas para el envío {envio['_id']}")

    azar = random.Random(contenedor_id)
    inicio = envio["fecha_creacion"] + timedelta(hours=1)
    lecturas = []

    for indice in range(MEDICIONES_POR_CONTENEDOR):
        proporcion = indice / (MEDICIONES_POR_CONTENEDOR - 1)

        lat = origen[0] + (destino[0] - origen[0]) * proporcion
        lon = origen[1] + (destino[1] - origen[1]) * proporcion

        documento = {
            "_id": f"tp-iot-prueba-v1-{contenedor_id}-{indice:03d}",
            "sensor_id": sensor["id"],
            "contenedor_id": contenedor_id,
            "fecha_hora": inicio + timedelta(minutes=5 * indice),
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "bateria": round(99 - indice * 0.08, 1),
        }

        if sensor["tipo"] in ("MULTI", "TEMPERATURA"):
            media = 5.0 if float(sensor["temp_max"]) <= 10 else 20.0
            documento["temperatura"] = round(
                media + azar.uniform(-0.8, 0.8), 2
            )

        if sensor["tipo"] in ("MULTI", "HUMEDAD"):
            documento["humedad"] = round(
                70 + azar.uniform(-5, 5), 1
            )

        if sensor["tipo"] in ("MULTI", "VIBRACION"):
            documento["vibracion"] = round(
                azar.uniform(0.1, 0.4), 3
            )

        lecturas.append(documento)

    return lecturas


def main():
    app = crear_aplicacion()

    try:
        repositorio = RepositorioRelacional(app.conexiones)

        clientes = [
            cliente for cliente in repositorio.listar_clientes()
            if cliente["estado"] == "ACTIVO"
        ]

        envios = list(app.conexiones.mongo().envios.find())
        sensores = repositorio.listar_sensores()

        seleccion = seleccionar_sensores(clientes, envios, sensores)

        documentos = []

        for cliente, envio, contenedor_id, sensor in seleccion:
            documentos.extend(
                construir_lecturas(cliente, envio, contenedor_id, sensor)
            )

        coleccion = app.conexiones.mongo().lecturas

        operaciones = [
            UpdateOne(
                {"_id": documento["_id"]},
                {"$setOnInsert": documento},
                upsert=True,
            )
            for documento in documentos
        ]

        resultado = coleccion.bulk_write(operaciones, ordered=False)

        total = coleccion.count_documents({
            "_id": {"$regex": "^tp-iot-prueba-v1-"}
        })

        print(f"Clientes con contenedor y sensor: {len(seleccion)}")
        print(f"Mediciones nuevas: {resultado.upserted_count}")
        print(f"Mediciones de esta carga guardadas: {total}")

    finally:
        app.cerrar()


if __name__ == "__main__":
    main()
