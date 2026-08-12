"""Serie historica de precios: una sola tabla larga, append-only.

`data/serie.csv` guarda una fila por (fecha, fuente, tienda, ean). Formato largo
y no una columna por tienda porque las tiendas y los productos cambian: una
tienda nueva es una fila nueva, no una migracion de esquema.

Dos fuentes conviven en la misma tabla, siempre etiquetadas:

  pedidosya  lo que Matias realmente paga. Es la que manda para decidir.
  sepa       precio de gondola de Carrefour y las demas cadenas. Se publica
             todos los dias y gratis, asi que da la serie densa que la captura
             de PedidosYa no puede dar. Sirve para detectar que un producto
             entro en ciclo de promocion, no para decidir el precio.

Uso:
    python src/store.py py                  # ingesta el ultimo data/py/py-*.json
    python src/store.py py data/py/py-2026-08-12.json
    python src/store.py sepa                # baja el ZIP de hoy y lo ingesta
    python src/store.py sepa ruta/al.zip
    python src/store.py seed               # los 7 ZIP = una semana de historia
"""

from __future__ import annotations

import csv
import json
import re
import zipfile
import sys
import urllib.request
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sepa import (LA_PLATA, WEEKDAY_NAMES, ParseStats, daily_url,
                  read_branches, read_prices)

ROOT = Path(__file__).resolve().parent.parent
SERIE = ROOT / "data" / "serie.csv"
PY_DIR = ROOT / "data" / "py"

COLUMNS = [
    "fecha", "fuente", "tienda", "item", "ean", "nombre",
    "precio", "precio_antes", "precio_por_unidad", "unidad", "contenido",
    "stock", "promo_tag", "sin_confirmar",
]


def load() -> list[dict]:
    if not SERIE.exists():
        return []
    with SERIE.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def save(rows: list[dict]) -> None:
    SERIE.parent.mkdir(parents=True, exist_ok=True)
    with SERIE.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def upsert(nuevas: list[dict], fecha: str, fuente: str) -> int:
    """Reemplaza la particion (fecha, fuente) entera.

    Correr dos veces el mismo dia tiene que dejar el mismo resultado que
    correrlo una sola vez; si no, un reintento despues de un error duplica el
    dia y ensucia la mediana para siempre.
    """
    viejas = [r for r in load() if not (r["fecha"] == fecha and r["fuente"] == fuente)]
    todas = viejas + nuevas
    todas.sort(key=lambda r: (r["fecha"], r["fuente"], r["tienda"], r["ean"]))
    save(todas)
    return len(nuevas)


def basket() -> dict:
    return yaml.safe_load((ROOT / "basket.yaml").read_text(encoding="utf-8"))


def ingest_py(path: Path) -> tuple[str, list[dict]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    fecha = doc["fecha"]
    rows = []
    for f in doc["filas"]:
        if f.get("precio") is None:
            continue  # sin precio no aporta nada a la serie
        rows.append({
            "fecha": fecha,
            "fuente": "pedidosya",
            "tienda": f.get("tienda", ""),
            "item": f.get("item", ""),
            "ean": f.get("ean", ""),
            "nombre": f.get("nombre", ""),
            "precio": f.get("precio"),
            "precio_antes": f.get("precio_antes") or "",
            "precio_por_unidad": f.get("precio_por_unidad") or "",
            "unidad": f.get("unidad") or "",
            "contenido": f.get("contenido") or "",
            "stock": f.get("stock") if f.get("stock") is not None else "",
            "promo_tag": f.get("promo_tag") or "",
            "sin_confirmar": "1" if f.get("sin_confirmar") else "",
        })
    return fecha, rows


def eans_de_interes() -> dict[str, str]:
    """EAN -> id de item. Union de los confirmados a mano y los que ya vio PeYa.

    Los `accepted_eans` de basket.yaml solos alcanzarian, pero son pocos todavia.
    Sumar lo que PedidosYa ya devolvio hace que SEPA empiece a juntar historia de
    esos productos desde hoy, antes de que Matias termine de confirmarlos.
    """
    mapa: dict[str, str] = {}
    for item in basket()["items"]:
        for ean in item.get("accepted_eans") or []:
            mapa[str(ean).lstrip("0")] = item["id"]
    for r in load():
        if r["fuente"] == "pedidosya" and r["ean"]:
            mapa.setdefault(r["ean"], r["item"])
    return mapa


FECHA_RE = re.compile(r"(20\d\d-\d\d-\d\d)")


def fecha_del_archivo(archive: Path) -> str:
    """La fecha que trae el ZIP adentro, NO la de hoy.

    El ZIP de cada dia de semana se pisa una vez por semana, y el que se baja
    hoy puede tener datos de hace hasta 7 dias: bajado el miercoles 2026-08-12,
    `sepa_miercoles.zip` traia adentro la carpeta `2026-08-05/`. Fechar eso como
    hoy corre la serie entera hasta una semana y arruina cualquier mediana, sin
    que se note nunca.

    Efecto util del mismo mecanismo: los 7 ZIP de la semana son 7 fechas
    distintas, asi que se puede sembrar una semana de historia de una sola vez.
    """
    with zipfile.ZipFile(archive) as z:
        for nombre in z.namelist():
            m = FECHA_RE.search(nombre)
            if m:
                return m.group(1)
    raise SystemExit(f"No se pudo leer la fecha de {archive.name}; no se ingesta a ciegas.")


def ingest_sepa(archive: Path) -> tuple[str, list[dict]]:
    spec = basket()
    mapa = eans_de_interes()
    if not mapa:
        raise SystemExit("No hay EANs para seguir todavia. Corre primero `store.py py`.")

    fecha = fecha_del_archivo(archive)
    stats = ParseStats()
    branches = read_branches(archive, centre=LA_PLATA,
                             radius_km=spec["meta"]["radio_km"], stats=stats)
    bandera = {(b.id_comercio, b.id_bandera): b.bandera for b in branches}

    # Una misma bandera tiene varias sucursales cerca; se guarda la mas barata
    # del dia, que es la que Matias podria ir a buscar.
    mejor: dict[tuple[str, str], dict] = {}
    for row in read_prices(archive, branches, eans=set(mapa), stats=stats):
        precio = row.precio_promo or row.precio_lista
        if not precio or precio <= 1:
            continue  # el feed trae ceros y precios de un centesimo del real
        tienda = bandera.get((row.id_comercio, row.id_bandera), "?")
        clave = (tienda, row.ean)
        previo = mejor.get(clave)
        if previo is None or precio < previo["precio"]:
            mejor[clave] = {
                "fecha": fecha,
                "fuente": "sepa",
                "tienda": tienda,
                "item": mapa.get(row.ean, ""),
                "ean": row.ean,
                "nombre": row.descripcion,
                "precio": precio,
                "precio_antes": row.precio_lista if row.precio_promo else "",
                "precio_por_unidad": "",
                "unidad": "",
                "contenido": "",
                "stock": "",
                "promo_tag": row.leyenda_promo,
                "sin_confirmar": "",
            }
    return fecha, list(mejor.values())


def cmd_seed() -> None:
    """Siembra una semana de historia de una sola vez.

    SEPA publica 7 ZIP, uno por dia de semana, y cada uno se pisa una vez por
    semana. O sea que en cualquier momento los 7 juntos son los ultimos 7 dias.
    Sin esto hay que esperar 10 dias corridos para que el veredicto de "cuando"
    diga algo; con esto, arranca hoy.

    Se baja de a uno y se borra despues de ingestarlo: son ~300 MB cada uno y no
    tiene sentido dejar 2 GB en disco.
    """
    destino = ROOT / "data" / "sepa-seed.zip"
    for wd in range(7):
        url = daily_url(wd)
        print(f"bajando {WEEKDAY_NAMES[wd]}...", flush=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=600) as r, destino.open("wb") as fh:
                while chunk := r.read(1 << 20):
                    fh.write(chunk)
            fecha, rows = ingest_sepa(destino)
            upsert(rows, fecha, "sepa")
            print(f"  {WEEKDAY_NAMES[wd]}: {len(rows)} filas para {fecha}", flush=True)
        except Exception as e:
            # Un dia que falle no invalida los otros seis.
            print(f"  {WEEKDAY_NAMES[wd]}: FALLO ({type(e).__name__}: {e})", flush=True)
        finally:
            destino.unlink(missing_ok=True)

    filas = load()
    fechas = sorted({r["fecha"] for r in filas if r["fuente"] == "sepa"})
    print(f"\nserie: {len(filas)} filas | fechas de SEPA: {', '.join(fechas)}")


def descargar_sepa() -> Path:
    url = daily_url(date.today().weekday())
    destino = ROOT / "data" / "sepa-hoy.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r, destino.open("wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)
    return destino


def main() -> None:
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if modo == "py":
        path = Path(arg) if arg else max(PY_DIR.glob("py-*.json"), default=None)
        if not path:
            raise SystemExit("No hay data/py/py-*.json. Corre `py_fetch.py daily`.")
        fecha, rows = ingest_py(path)
    elif modo == "seed":
        cmd_seed()
        return
    elif modo == "sepa":
        archive = Path(arg) if arg else descargar_sepa()
        fecha, rows = ingest_sepa(archive)
    else:
        raise SystemExit(__doc__)

    n = upsert(rows, fecha, modo if modo == "sepa" else "pedidosya")
    total = len(load())
    dias = len({r["fecha"] for r in load()})
    print(f"{n} filas de {modo} para {fecha}")
    print(f"serie.csv: {total} filas, {dias} dia(s) distintos")


if __name__ == "__main__":
    main()
