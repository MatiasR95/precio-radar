"""Lectura del feed diario SEPA (Precios Claros).

El feed es un ZIP de ~300 MB que contiene un ZIP por comercio, y cada uno de esos
trae comercio.csv, sucursales.csv y productos.csv separados por "|".

Todo se procesa en streaming: nunca se carga productos.csv entero en memoria.

Cosas que el feed hace y hay que tolerar (verificado contra el archivo del
2026-08-11):

- Un comercio puede publicar un ZIP vacio (0 bytes). Se saltea y se reporta.
- Cada CSV termina con lineas en blanco; comercio.csv ademas trae una fila
  fantasma con todos los campos vacios.
- Alberdi S.A. (Comodin) publica ~107 filas de sucursales con saltos de linea
  dentro de los campos. Se descartan por fila, no se aborta el archivo.
- Un mismo id_comercio agrupa varias banderas: Cencosud = Vea/Disco/Jumbo,
  INC = Carrefour Hipermercado/Maxi/Express/Market, DORINKA = ChangoMas.
  Siempre agrupar por (id_comercio, id_bandera), nunca por id_comercio solo.
- Algunos comercios (ej. DEHEZA) ponen el codigo de barras en id_producto y un
  flag en productos_ean. Por eso el EAN se resuelve mirando los dos campos.
"""

from __future__ import annotations

import csv
import io
import math
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# El ZIP diario se publica por dia de semana y se pisa cada semana.
WEEKDAY_RESOURCES = {
    0: "0a9069a9-06e8-4f98-874d-da5578693290",  # lunes
    1: "9dc06241-cc83-44f4-8e25-c9b1636b8bc8",  # martes
    2: "1e92cd42-4f94-4071-a165-62c4cb2ce23c",  # miercoles
    3: "d076720f-a7f0-4af8-b1d6-1b99d5a90c14",  # jueves
    4: "91bc072a-4726-44a1-85ec-4a8467aad27e",  # viernes
    5: "b3c3da5d-213d-41e7-8d74-f23fda0a3c30",  # sabado
    6: "f8e75128-515a-436e-bf8d-5c63a62f2005",  # domingo
}
WEEKDAY_NAMES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DATASET_ID = "6f47ec76-d1ce-4e34-a7e1-621fe9b1d0b5"
BASE = "https://datos.produccion.gob.ar/dataset"

LA_PLATA = (-34.9214, -57.9544)


def daily_url(weekday: int) -> str:
    """URL del ZIP correspondiente a un dia de semana (0=lunes)."""
    name = WEEKDAY_NAMES[weekday]
    return f"{BASE}/{DATASET_ID}/resource/{WEEKDAY_RESOURCES[weekday]}/download/sepa_{name}.zip"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r1, r2 = math.radians(lat1), math.radians(lat2)
    d = math.radians(lon2 - lon1)
    cos = math.sin(r1) * math.sin(r2) + math.cos(r1) * math.cos(r2) * math.cos(d)
    return 6371.0 * math.acos(max(-1.0, min(1.0, cos)))


@dataclass
class Branch:
    id_comercio: str
    id_bandera: str
    id_sucursal: str
    bandera: str
    razon_social: str
    nombre: str
    localidad: str
    provincia: str
    lat: float
    lon: float
    distancia_km: float

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.id_comercio, self.id_bandera, self.id_sucursal)


@dataclass
class PriceRow:
    id_comercio: str
    id_bandera: str
    id_sucursal: str
    ean: str
    descripcion: str
    marca: str
    precio_lista: float | None
    precio_promo: float | None
    leyenda_promo: str
    cantidad_presentacion: str
    unidad_presentacion: str


@dataclass
class ParseStats:
    comercios_vacios: list[str] = field(default_factory=list)
    filas_sucursales_descartadas: int = 0
    filas_productos_descartadas: int = 0


def _rows(zf: zipfile.ZipFile, filename: str) -> Iterator[dict[str, str]]:
    """Lee un CSV del ZIP salteando filas con cantidad de columnas incorrecta."""
    with zf.open(filename) as raw:
        stream = io.TextIOWrapper(raw, "utf-8-sig", errors="replace", newline="")
        header_line = stream.readline().rstrip("\r\n")
        header = header_line.split("|")
        for line in stream:
            fields = line.rstrip("\r\n").split("|")
            if len(fields) != len(header) or not fields[0].strip():
                # Fila corrupta o linea en blanco final: se cuenta afuera.
                yield {"__malformed__": line[:200]}
                continue
            yield dict(zip(header, fields))


def _member(zf: zipfile.ZipFile, basename: str) -> str | None:
    for name in zf.namelist():
        if name.rsplit("/", 1)[-1] == basename:
            return name
    return None


def _float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def resolve_ean(row: dict[str, str]) -> str | None:
    """Devuelve el codigo de barras real de una fila de productos.csv.

    La mayoria de los comercios lo publica en productos_ean, pero algunos (ej.
    DEHEZA) lo ponen en id_producto y dejan un flag en productos_ean. Se toma el
    primer campo que parezca un EAN (>=8 digitos).
    """
    for candidate in (row.get("productos_ean"), row.get("id_producto")):
        digits = (candidate or "").strip()
        if digits.isdigit() and len(digits) >= 8:
            return digits.lstrip("0") or digits
    return None


def iter_comercio_zips(archive: Path) -> Iterator[tuple[str, zipfile.ZipFile | None]]:
    """Itera los ZIP internos, uno por comercio. Devuelve None si esta vacio."""
    with zipfile.ZipFile(archive) as outer:
        for name in outer.namelist():
            if not name.endswith(".zip"):
                continue
            payload = outer.read(name)
            if not payload:
                yield name, None
                continue
            yield name, zipfile.ZipFile(io.BytesIO(payload))


def read_branches(
    archive: Path,
    centre: tuple[float, float] = LA_PLATA,
    radius_km: float = 25.0,
    stats: ParseStats | None = None,
) -> list[Branch]:
    """Sucursales dentro de un radio, agrupadas correctamente por bandera.

    Se filtra por coordenadas y no por nombre de localidad: DIA publica todas sus
    sucursales con localidad "BUENOS AIRES", asi que filtrar por texto pierde las
    20 sucursales que tiene en La Plata.
    """
    stats = stats if stats is not None else ParseStats()
    lat0, lon0 = centre
    found: list[Branch] = []

    for name, inner in iter_comercio_zips(archive):
        if inner is None:
            stats.comercios_vacios.append(name)
            continue

        comercio_file = _member(inner, "comercio.csv")
        sucursales_file = _member(inner, "sucursales.csv")
        if not comercio_file or not sucursales_file:
            continue

        banderas: dict[tuple[str, str], tuple[str, str]] = {}
        for row in _rows(inner, comercio_file):
            if "__malformed__" in row:
                continue
            key = (row["id_comercio"], row["id_bandera"])
            banderas[key] = (
                (row.get("comercio_bandera_nombre") or "").strip()
                or (row.get("comercio_razon_social") or "").strip(),
                (row.get("comercio_razon_social") or "").strip(),
            )

        for row in _rows(inner, sucursales_file):
            if "__malformed__" in row:
                stats.filas_sucursales_descartadas += 1
                continue
            lat = _float(row.get("sucursales_latitud"))
            lon = _float(row.get("sucursales_longitud"))
            if lat is None or lon is None or not (-90 < lat < 90) or not (-180 < lon < 180):
                stats.filas_sucursales_descartadas += 1
                continue
            distance = haversine_km(lat0, lon0, lat, lon)
            if distance > radius_km:
                continue
            key = (row["id_comercio"], row["id_bandera"])
            bandera, razon = banderas.get(key, ("?", "?"))
            found.append(
                Branch(
                    id_comercio=row["id_comercio"],
                    id_bandera=row["id_bandera"],
                    id_sucursal=row["id_sucursal"],
                    bandera=bandera,
                    razon_social=razon,
                    nombre=(row.get("sucursales_nombre") or "").strip(),
                    localidad=(row.get("sucursales_localidad") or "").strip(),
                    provincia=(row.get("sucursales_provincia") or "").strip(),
                    lat=lat,
                    lon=lon,
                    distancia_km=round(distance, 2),
                )
            )

    found.sort(key=lambda b: b.distancia_km)
    return found


def read_prices(
    archive: Path,
    branches: list[Branch],
    eans: set[str] | None = None,
    stats: ParseStats | None = None,
) -> Iterator[PriceRow]:
    """Precios de las sucursales dadas, opcionalmente filtrados por EAN.

    Con eans=None devuelve todo el catalogo de esas sucursales (util para armar
    basket.yaml); con un set de EANs devuelve solo la canasta.
    """
    stats = stats if stats is not None else ParseStats()
    wanted = {b.key for b in branches}
    wanted_by_comercio: dict[str, set[str]] = {}
    for comercio, bandera, sucursal in wanted:
        wanted_by_comercio.setdefault(comercio, set()).add(sucursal)
    normalised_eans = {e.lstrip("0") or e for e in eans} if eans else None

    for name, inner in iter_comercio_zips(archive):
        if inner is None:
            stats.comercios_vacios.append(name)
            continue
        productos_file = _member(inner, "productos.csv")
        if not productos_file:
            continue

        for row in _rows(inner, productos_file):
            if "__malformed__" in row:
                stats.filas_productos_descartadas += 1
                continue
            sucursales = wanted_by_comercio.get(row.get("id_comercio", ""))
            if not sucursales or row.get("id_sucursal") not in sucursales:
                continue
            if (row["id_comercio"], row.get("id_bandera", ""), row["id_sucursal"]) not in wanted:
                continue
            ean = resolve_ean(row)
            if ean is None:
                continue
            if normalised_eans is not None and ean not in normalised_eans:
                continue
            yield PriceRow(
                id_comercio=row["id_comercio"],
                id_bandera=row.get("id_bandera", ""),
                id_sucursal=row["id_sucursal"],
                ean=ean,
                descripcion=(row.get("productos_descripcion") or "").strip(),
                marca=(row.get("productos_marca") or "").strip(),
                precio_lista=_float(row.get("productos_precio_lista")),
                precio_promo=_float(row.get("productos_precio_unitario_promo1")),
                leyenda_promo=(row.get("productos_leyenda_promo1") or "").strip(),
                cantidad_presentacion=(row.get("productos_cantidad_presentacion") or "").strip(),
                unidad_presentacion=(row.get("productos_unidad_medida_presentacion") or "").strip(),
            )
