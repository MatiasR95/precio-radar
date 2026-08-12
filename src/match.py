"""Busca candidatos de la canasta dentro del catalogo SEPA de La Plata.

La mayoria de las lineas de basket.yaml no son un producto fijo sino una regla
("papel higienico doble hoja, el mas barato"). Este script traduce esas reglas a
candidatos concretos con precio por unidad, para que Matias confirme cuales
valen y cuales no. Los confirmados se congelan despues en basket.yaml.

Uso:
    python src/match.py <ruta_al_zip> [id_item]
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import yaml

from sepa import LA_PLATA, ParseStats, read_branches, read_prices

ROOT = Path(__file__).resolve().parent.parent

# A unidad base: peso -> kg, volumen -> L, largo -> m, resto -> un.
UNIT_FACTORS = {
    "gr": ("kg", 0.001), "g": ("kg", 0.001), "grs": ("kg", 0.001), "gramos": ("kg", 0.001),
    "grm": ("kg", 0.001), "grms": ("kg", 0.001), "grss": ("kg", 0.001),
    "kg": ("kg", 1.0), "kgm": ("kg", 1.0), "kilo": ("kg", 1.0), "kilogramo": ("kg", 1.0),
    "ml": ("L", 0.001), "cc": ("L", 0.001), "cm3": ("L", 0.001),
    "lt": ("L", 1.0), "l": ("L", 1.0), "lts": ("L", 1.0), "litro": ("L", 1.0),
    "mt": ("m", 1.0), "m": ("m", 1.0), "mts": ("m", 1.0), "metro": ("m", 1.0),
    "cm": ("m", 0.01),
    "un": ("un", 1.0), "unidad": ("un", 1.0), "unidades": ("un", 1.0), "u": ("un", 1.0),
}


def norm(text: str) -> str:
    """Minusculas y sin acentos: el feed mezcla 'MAÑANITA', 'Mananita', 'MA?ANITA'."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().replace("ñ", "n").split())


def to_base(cantidad: str, unidad: str) -> tuple[str, float] | None:
    try:
        qty = float(cantidad)
    except (TypeError, ValueError):
        return None
    if qty <= 0:
        return None
    key = norm(unidad).rstrip(".")
    if key not in UNIT_FACTORS:
        return None
    base, factor = UNIT_FACTORS[key]
    # Convencion rota y frecuente: publican "0.75" con unidad "ml" queriendo decir
    # 0,75 L, o "0.18" con "gr" por 180 g. Sin esto el precio por unidad sale 1000x.
    if factor == 0.001 and qty < 10:
        factor = 1.0
    return base, qty * factor


SIZE_RE = re.compile(
    r"(?<![\d.,])(\d{1,5}(?:[.,]\d{1,3})?)\s*"
    r"(kgs?|kilos?|grms?|grs?|gramos?|g|mls?|cc|lts?|litros?|l|mts?|metros?|m|un|u)(?![a-z])"
)
PACK_RE = re.compile(r"(\d{1,3})\s*[x*]\s*(\d{1,5}(?:[.,]\d{1,3})?)\s*"
                     r"(kgs?|grs?|g|mls?|cc|lts?|l|mts?|m|un|u|panos?|pa.os?)?(?![a-z])")


def size_from_text(text: str) -> tuple[str, float] | None:
    """Saca la presentacion del texto de la descripcion.

    Muchas filas no traen cantidad_presentacion usable pero si dicen el tamano en
    la descripcion ("YERBA MANANITA 4FLEX X 1 KG", "POT-180-gr.", "3 X 100 panos").
    Se prefiere el pack (3x100) porque define el total real del paquete.
    """
    pack = PACK_RE.search(text)
    if pack:
        count = float(pack.group(1))
        each = float(pack.group(2).replace(",", "."))
        unit = (pack.group(3) or "un").rstrip(".")
        if unit.startswith("pan") or unit.startswith("pa"):
            unit = "un"
        if unit in UNIT_FACTORS:
            base, factor = UNIT_FACTORS[unit]
            if factor == 0.001 and each < 10:
                factor = 1.0
            total = count * each * factor
            if total > 0:
                return base, total

    best: tuple[str, float] | None = None
    for value, unit in SIZE_RE.findall(text):
        unit = unit.rstrip(".")
        if unit not in UNIT_FACTORS:
            continue
        qty = float(value.replace(",", "."))
        base, factor = UNIT_FACTORS[unit]
        if factor == 0.001 and qty < 10:
            factor = 1.0
        total = qty * factor
        if total <= 0:
            continue
        # Ante varios numeros en la descripcion gana el mas grande: suele ser la
        # presentacion y no el codigo, el porcentaje de grasa o la cantidad de hojas.
        if best is None or total > best[1]:
            best = (base, total)
    return best


def resolve_size(row_text: str, cantidad: str, unidad: str) -> tuple[str, float] | None:
    """Combina ambas fuentes de tamano y se queda con la mas creible."""
    from_fields = to_base(cantidad, unidad)
    from_text = size_from_text(row_text)
    if from_fields and from_text:
        # Si coinciden en unidad y difieren por un factor ~1000, gana el texto:
        # el error tipico es de convencion en los campos, no en la descripcion.
        if from_fields[0] == from_text[0]:
            ratio = from_fields[1] / from_text[1] if from_text[1] else 1
            return from_text if (ratio > 50 or ratio < 0.02) else from_fields
        return from_text
    return from_fields or from_text


def matches(text: str, rules: dict) -> bool:
    match = rules.get("match", {})
    all_terms = [norm(t) for t in match.get("all", [])]
    any_terms = [norm(t) for t in match.get("any", [])]
    none_terms = [norm(t) for t in match.get("none", [])]
    variants = [norm(t) for t in rules.get("acepta_variantes", [])]

    core = all(t in text for t in all_terms) if all_terms else True
    if not core and variants:
        core = any(v in text for v in variants)
    if not core:
        return False
    if any_terms and not any(t in text for t in any_terms):
        return False
    if none_terms and any(t in text for t in none_terms):
        return False
    required = [norm(t) for t in rules.get("requiere", [])]
    if required and not all(t in text for t in required):
        return False
    required_any = [norm(t) for t in rules.get("requiere_alguno", [])]
    if required_any and not any(t in text for t in required_any):
        return False
    return True


def main(archive_path: str, only_item: str | None = None) -> None:
    spec = yaml.safe_load((ROOT / "basket.yaml").read_text(encoding="utf-8"))
    items = [i for i in spec["items"] if not only_item or i["id"] == only_item]
    if not items:
        raise SystemExit(f"no existe el item {only_item!r} en basket.yaml")

    archive = Path(archive_path)
    stats = ParseStats()
    branches = read_branches(archive, centre=LA_PLATA, radius_km=spec["meta"]["radio_km"], stats=stats)
    bandera_de = {(b.id_comercio, b.id_bandera): b.bandera for b in branches}
    print(f"{len(branches)} sucursales, {len(bandera_de)} banderas\n")

    # cand[item][ean] = {descripcion, banderas: {bandera: mejor_precio}, unidad, por_unidad}
    cand: dict[str, dict[str, dict]] = {i["id"]: defaultdict(dict) for i in items}

    for row in read_prices(archive, branches, eans=None, stats=stats):
        price = row.precio_promo or row.precio_lista
        if not price or price <= 1:
            continue  # el feed trae ceros y precios de un centesimo del real
        text = norm(f"{row.descripcion} {row.marca}")
        base = resolve_size(text, row.cantidad_presentacion, row.unidad_presentacion)
        bandera = bandera_de.get((row.id_comercio, row.id_bandera), "?")

        for item in items:
            if not matches(text, item):
                continue
            size = item.get("tamano")
            if size and base:
                if base[0] != size["unidad"] or not (size["min"] <= base[1] <= size["max"]):
                    continue
            entry = cand[item["id"]].setdefault(
                row.ean,
                {
                    "descripcion": f"{row.descripcion} [{row.marca}]".strip(),
                    "banderas": {},
                    "base": base,
                },
            )
            prev = entry["banderas"].get(bandera)
            if prev is None or price < prev:
                entry["banderas"][bandera] = price

    salida = {}
    for item in items:
        found = cand[item["id"]]
        print("=" * 78)
        print(f"{item['nombre']}   ({item['id']})")
        if not found:
            print("  SIN CANDIDATOS — hay que aflojar las reglas de match\n")
            salida[item["id"]] = []
            continue

        rows = []
        for ean, entry in found.items():
            best = min(entry["banderas"].values())
            base = entry["base"]
            per_unit = (best / base[1]) if base and base[1] else None
            rows.append((per_unit, best, ean, entry, base))
        # Descarta outliers de precio por unidad dentro del mismo item. Sin esto el
        # primer puesto se lo lleva siempre un error de carga (lavandina a $49/L).
        with_unit = sorted(r[0] for r in rows if r[0])
        if len(with_unit) >= 5:
            median = with_unit[len(with_unit) // 2]
            descartados = [r for r in rows if r[0] and not (median / 8 <= r[0] <= median * 8)]
            rows = [r for r in rows if not (r[0] and not (median / 8 <= r[0] <= median * 8))]
            if descartados:
                print(f"  ({len(descartados)} candidatos descartados por precio/unidad inverosimil)")

        # Ordena por precio por unidad; los que no tienen presentacion usable van al final.
        rows.sort(key=lambda r: (r[0] is None, r[0] if r[0] is not None else 0))

        print(f"  {len(found)} candidatos distintos. Los 8 mas baratos por unidad:")
        for per_unit, best, ean, entry, base in rows[:8]:
            unit = f"{per_unit:>10,.0f}/{base[0]}" if per_unit else "        s/d"
            tiendas = ", ".join(
                f"{b.split()[0][:11]} ${p:,.0f}" for b, p in sorted(entry["banderas"].items(), key=lambda kv: kv[1])[:4]
            )
            print(f"   {unit}  {entry['descripcion'][:44]:44} {tiendas}")
        print()
        salida[item["id"]] = [
            {
                "ean": ean,
                "descripcion": entry["descripcion"],
                "precio_min": best,
                "por_unidad": per_unit,
                "unidad": base[0] if base else None,
                "banderas": entry["banderas"],
            }
            for per_unit, best, ean, entry, base in rows[:25]
        ]

    out = ROOT / "data" / "candidatos.json"
    out.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
