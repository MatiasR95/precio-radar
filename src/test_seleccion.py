"""Prueba la seleccion de variantes contra respuestas reales ya capturadas.

PedidosYa bloquea si se le insiste, asi que la logica no se puede probar
pegandole a la API cada vez que se toca una regla. Este script reusa las
respuestas de `discover` como fixture: son respuestas de verdad, del dia que se
capturaron, y alcanzan para saber si una regla deja pasar lo que no debe.

    python src/test_seleccion.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from py_fetch import norm_gtin, seleccionar

ROOT = Path(__file__).resolve().parent.parent


def fixtures() -> list[dict]:
    """Todos los productos que aparecieron en las capturas, deduplicados."""
    archivos = sorted((ROOT / "data" / "py").glob("discovery-*.json"))
    if not archivos:
        raise SystemExit("No hay data/py/discovery-*.json para probar.")
    por_ean: dict[str, dict] = {}
    for archivo in archivos:
        doc = json.loads(archivo.read_text(encoding="utf-8"))
        for cap in doc["captures"]:
            path = urllib.parse.urlsplit(cap["url"]).path
            body = cap["body"]
            # La busqueda usa snake_case y trae `data`; el listado y el detalle
            # usan camelCase con `pricing` anidado. Solo sirven los primeros,
            # que son la forma que ve `seleccionar`.
            if "/search" not in path or not isinstance(body, dict):
                continue
            for r in body.get("data") or []:
                if r.get("gtin"):
                    por_ean[norm_gtin(r["gtin"])] = r
    return list(por_ean.values())


def main() -> None:
    spec = yaml.safe_load((ROOT / "basket.yaml").read_text(encoding="utf-8"))
    catalogo = fixtures()
    print(f"{len(catalogo)} productos distintos en las capturas\n")

    fallos = 0
    for item in spec["items"]:
        elegidos = seleccionar(catalogo, item)
        aceptados = {str(e).lstrip("0") for e in (item.get("accepted_eans") or [])}
        confirmados = [r for r in elegidos if norm_gtin(r["gtin"]) in aceptados]
        print(f"{item['id']}  ->  {len(elegidos)} variante(s), {len(confirmados)} confirmada(s)")
        for r in sorted(elegidos, key=lambda r: r.get("price") or 0)[:6]:
            marca = "OK " if norm_gtin(r["gtin"]) in aceptados else "  ?"
            cant = r.get("content_quantity")
            print(f"   {marca} ${r.get('price'):>10,.0f}  x{cant}  {str(r.get('name'))[:52]}")

        # Lo que no tiene que pasar nunca: un rechazado explicito colandose.
        rechazados = {str(e).lstrip("0") for e in (item.get("rejected_eans") or [])}
        colados = [r for r in elegidos if norm_gtin(r["gtin"]) in rechazados]
        if colados:
            fallos += 1
            print(f"   FALLA: {len(colados)} EAN rechazado(s) se colaron")
        print()

    print("FALLAS:", fallos)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
