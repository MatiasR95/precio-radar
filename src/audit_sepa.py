"""Fase 0: que sucursales y que productos hay realmente cerca de La Plata.

Uso:
    python src/audit_sepa.py <ruta_al_zip>

Escribe data/branches_la_plata.json y muestra:
  1. sucursales por bandera dentro del radio
  2. cuantos EAN publica cada bandera
  3. los productos comparables entre mas banderas (candidatos para basket.yaml)
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from sepa import LA_PLATA, ParseStats, read_branches, read_prices

ROOT = Path(__file__).resolve().parent.parent


def main(archive_path: str, radius_km: float = 25.0) -> None:
    archive = Path(archive_path)
    stats = ParseStats()

    branches = read_branches(archive, centre=LA_PLATA, radius_km=radius_km, stats=stats)
    print(f"Sucursales a <= {radius_km:.0f} km del centro de La Plata: {len(branches)}\n")

    by_bandera: dict[tuple[str, str], list] = defaultdict(list)
    for branch in branches:
        by_bandera[(branch.id_comercio, branch.id_bandera)].append(branch)

    print(f"{'bandera':34} {'id':>7}  {'suc':>4}  mas cercana")
    for key, group in sorted(by_bandera.items(), key=lambda kv: -len(kv[1])):
        label = group[0].bandera[:34]
        nearest = group[0]
        print(
            f"{label:34} {key[0]:>3}.{key[1]:<3} {len(group):4}  "
            f"{nearest.distancia_km:5.1f} km  {nearest.nombre[:24]}"
        )

    out = ROOT / "data" / "branches_la_plata.json"
    out.write_text(
        json.dumps([asdict(b) for b in branches], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n-> {out.relative_to(ROOT)} ({len(branches)} sucursales)")

    # Segunda pasada: catalogo completo de esas sucursales.
    print("\nLeyendo catalogo de esas sucursales (streaming)...")
    eans_por_bandera: dict[tuple[str, str], set[str]] = defaultdict(set)
    descripcion: dict[str, str] = {}
    precios: dict[str, list[float]] = defaultdict(list)
    total = 0

    for row in read_prices(archive, branches, eans=None, stats=stats):
        total += 1
        eans_por_bandera[(row.id_comercio, row.id_bandera)].add(row.ean)
        if row.ean not in descripcion and row.descripcion:
            descripcion[row.ean] = f"{row.descripcion} [{row.marca}]".strip()
        price = row.precio_promo or row.precio_lista
        if price:
            precios[row.ean].append(price)

    print(f"filas de precio leidas: {total:,}")
    print(f"EAN distintos: {len(descripcion):,}\n")

    print(f"{'bandera':34} {'EAN publicados':>15}")
    for key, eans in sorted(eans_por_bandera.items(), key=lambda kv: -len(kv[1])):
        label = next(b.bandera for b in branches if (b.id_comercio, b.id_bandera) == key)
        print(f"{label[:34]:34} {len(eans):15,}")

    # Un producto sirve para comparar solo si mas de una bandera lo publica.
    cobertura = Counter()
    for key, eans in eans_por_bandera.items():
        for ean in eans:
            cobertura[ean] += 1

    n_banderas = len(eans_por_bandera)
    comparables = [e for e, c in cobertura.items() if c >= 3]
    print(
        f"\nEAN publicados por >=3 de las {n_banderas} banderas: {len(comparables):,}"
        f"  (por las {n_banderas}: {sum(1 for c in cobertura.values() if c == n_banderas):,})"
    )

    # El feed trae precios basura (0, o un centesimo del precio real cuando el
    # comercio publica el precio por bulto mal). Sin este filtro el ranking de
    # dispersion queda dominado por errores de carga, no por ofertas reales.
    def sane(values: list[float]) -> list[float]:
        positive = [v for v in values if v and v > 1]
        if len(positive) < 3:
            return positive
        positive.sort()
        median = positive[len(positive) // 2]
        return [v for v in positive if median / 10 <= v <= median * 10]

    print("\nEjemplos comparables, con dispersion de precio entre sucursales:")
    ranked = sorted(
        (e for e in comparables if len(sane(precios[e])) >= 4),
        key=lambda e: (max(sane(precios[e])) - min(sane(precios[e]))) / min(sane(precios[e])),
        reverse=True,
    )
    print(f"{'EAN':>15} {'min':>10} {'max':>10} {'dif%':>7}  descripcion")
    for ean in ranked[:15]:
        values = sane(precios[ean])
        lo, hi = min(values), max(values)
        print(f"{ean:>15} {lo:10,.0f} {hi:10,.0f} {100 * (hi - lo) / lo:6.0f}%  {descripcion[ean][:44]}")

    candidates = ROOT / "data" / "ean_candidates.json"
    candidates.write_text(
        json.dumps(
            [
                {
                    "ean": ean,
                    "descripcion": descripcion.get(ean, ""),
                    "banderas": cobertura[ean],
                    "precio_min": round(min(sane(precios[ean])), 2),
                    "precio_max": round(max(sane(precios[ean])), 2),
                }
                for ean in sorted(comparables, key=lambda e: -cobertura[e])
                if len(sane(precios[ean])) >= 4
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"-> {candidates.relative_to(ROOT)}")

    if stats.comercios_vacios:
        print(f"\nComercios con ZIP vacio: {len(stats.comercios_vacios)}")
    print(
        f"Filas descartadas por formato: sucursales={stats.filas_sucursales_descartadas}, "
        f"productos={stats.filas_productos_descartadas}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
