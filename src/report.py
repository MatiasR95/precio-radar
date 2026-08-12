"""Reporte diario: donde conviene comprar hoy, y si hoy vale la pena comprar.

Son dos preguntas distintas y el reporte las separa a proposito:

  DONDE   comparacion del dia entre PeYa Market y Carrefour dentro de
          PedidosYa. Se contesta con la corrida de hoy sola.

  CUANDO  el precio de hoy contra la propia historia del producto. Es la unica
          que dice si un descuento es real o si es el precio de siempre con un
          cartel encima. Necesita dias acumulados: sin historia no se contesta,
          se dice que falta.

Uso:
    python src/report.py            # reporte de la ultima fecha en la serie
    python src/report.py 2026-08-12
"""

from __future__ import annotations

import statistics
import sys
from datetime import date, timedelta
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import load

ROOT = Path(__file__).resolve().parent.parent
SALIDA = ROOT / "data" / "reporte.md"
HTML = ROOT / "data" / "reporte.html"

# Debajo de esto la mediana y el percentil son ruido: con 3 datos, "el mas
# barato de la serie" no significa nada. Preferible decir que falta historia.
#
# 7 = un ciclo semanal completo, que es como se mueven las promos de super acá.
# Con 7 puntos cada dia pesa 14%, asi que el percentil es grueso: sirve para
# "hoy es el mas barato de la semana", no para diferencias finas. A medida que
# la serie crezca conviene subirlo a 30 y mirar el mes.
MIN_DIAS = 7
# Percentil a partir del cual se recomienda comprar: hoy tiene que estar en el
# 20% mas barato de lo visto.
UMBRAL_BARATO = 80.0


def num(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def pct_mas_caros(historia: list[float], hoy: float) -> float:
    """Que porcentaje de los precios pasados fue mas caro que el de hoy.

    90 significa que hoy solo lo superaron en baratura 1 de cada 10 dias.
    """
    if not historia:
        return 0.0
    return 100.0 * sum(1 for p in historia if p > hoy) / len(historia)


def serie_de(filas: list[dict], ean: str, fuente: str, tienda: str | None,
             hasta: str) -> list[float]:
    """Precios anteriores a `hasta` de un EAN. Un valor por dia, el mas barato."""
    por_dia: dict[str, float] = {}
    for r in filas:
        if r["ean"] != ean or r["fuente"] != fuente or r["fecha"] >= hasta:
            continue
        if tienda and r["tienda"] != tienda:
            continue
        p = num(r["precio"])
        if p is None:
            continue
        if r["fecha"] not in por_dia or p < por_dia[r["fecha"]]:
            por_dia[r["fecha"]] = p
    return list(por_dia.values())


# PedidosYa publica el precio por unidad en la unidad de cada ficha: dentro de
# una misma familia conviven $/g y $/kg, o $/ml y $/L. Se llevan todos a la
# unidad base para poder ordenarlos entre si.
CONVERSION = {
    "g": ("kg", 0.001), "gr": ("kg", 0.001), "grs": ("kg", 0.001), "kg": ("kg", 1.0),
    "ml": ("L", 0.001), "cc": ("L", 0.001), "l": ("L", 1.0), "lt": ("L", 1.0),
    "m": ("m", 1.0), "mt": ("m", 1.0),
    "un": ("un", 1.0), "u": ("un", 1.0), "sheets": ("un", 1.0),
}


def por_unidad(r: dict) -> tuple[str, float] | None:
    """(unidad base, precio por esa unidad). None si no se puede normalizar."""
    p = num(r.get("precio_por_unidad"))
    u = (r.get("unidad") or "").strip().lower()
    if p is None or p <= 0 or u not in CONVERSION:
        return None
    base, factor = CONVERSION[u]
    return base, p / factor


def ordenador(filas: list[dict]):
    """Devuelve una funcion de orden por precio por unidad, con el envase como
    ultimo recurso.

    Ordenar por el precio del paquete elige el paquete mas chico, no el mas
    conveniente: en papel higienico el mas barato era el pack de 4 a $2.459
    mientras existia uno de 18 a $15.510 que sale bastante menos por rollo. Solo
    se comparan entre si las filas que comparten unidad base; las demas caen al
    final y se ordenan por precio.
    """
    bases = [b for b, _ in filter(None, (por_unidad(r) for r in filas))]
    dominante = max(set(bases), key=bases.count) if bases else None

    def clave(r: dict):
        pu = por_unidad(r)
        if dominante and pu and pu[0] == dominante:
            return (0, pu[1])
        return (1, num(r.get("precio")) or float("inf"))

    return clave


def fecha_siguiente(f: str) -> str:
    """serie_de() corta con `fecha < hasta`; para incluir hoy hay que pedir mañana."""
    return (date.fromisoformat(f) + timedelta(days=1)).isoformat()


def mejor_por_tienda(filas: list[dict]) -> dict[str, dict]:
    """La fila mas barata de cada tienda, priorizando las confirmadas por EAN.

    Un candidato sin confirmar puede ser cualquier cosa que el buscador devolvio
    barata; si hay uno confirmado, gana el confirmado aunque salga mas.
    """
    clave = ordenador(filas)
    mejor: dict[str, dict] = {}
    for r in filas:
        if num(r["precio"]) is None:
            continue
        actual = mejor.get(r["tienda"])
        if actual is None:
            mejor[r["tienda"]] = r
            continue
        confirmada_gana = bool(actual["sin_confirmar"]) and not r["sin_confirmar"]
        empate_mas_barato = (bool(actual["sin_confirmar"]) == bool(r["sin_confirmar"])
                             and clave(r) < clave(actual))
        if confirmada_gana or empate_mas_barato:
            mejor[r["tienda"]] = r
    return mejor


def analizar(filas: list[dict], item: dict, fecha: str) -> dict:
    hoy = [r for r in filas
           if r["fecha"] == fecha and r["fuente"] == "pedidosya" and r["item"] == item["id"]]
    resultado = {"item": item, "tiendas": {}, "veredicto": None, "detalle": "",
                 "senal_sepa": None}
    if not hoy:
        resultado["detalle"] = "sin datos de PedidosYa hoy"
        return resultado

    resultado["tiendas"] = mejor_por_tienda(hoy)

    # Comparar el mas barato de cada tienda es comparar cualquier cosa: en yerba
    # daba Mañanita de 1 kg en PeYa contra Mañanita de 500 g en Carrefour y
    # anunciaba $2.411 de diferencia. La comparacion valida es del mismo EAN en
    # las dos tiendas; si no hay ninguno en comun, se dice y no se resta.
    # `variantes: false` = la linea es UN producto, no una familia. Se siguen
    # guardando las alternativas en la serie (son gratis y a veces son mas
    # baratas), pero no pueden convertirse en el precio de portada: para leche
    # Protein una marca competidora aparecia como si fuera la de siempre, $625
    # mas barata, y la comparacion entre tiendas dejaba de ser del mismo producto.
    sigue_variantes = item.get("variantes", True)
    base = hoy if sigue_variantes else [r for r in hoy if not r["sin_confirmar"]] or hoy

    por_tienda: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in base:
        p = num(r["precio"])
        if p is None:
            continue
        previo = por_tienda[r["tienda"]].get(r["ean"])
        if previo is None or p < num(previo["precio"]):
            por_tienda[r["tienda"]][r["ean"]] = r

    comunes: set[str] = set()
    for i, tienda in enumerate(por_tienda):
        comunes = set(por_tienda[tienda]) if i == 0 else comunes & set(por_tienda[tienda])
    resultado["comparable"] = bool(comunes) and len(por_tienda) > 1
    if resultado["comparable"]:
        # Entre los EAN que estan en las dos, el que salga mas barato en algun lado.
        clave_ean = ordenador([por_tienda[t][e] for t in por_tienda for e in comunes])
        ean_comun = min(comunes, key=lambda e: min(clave_ean(por_tienda[t][e]) for t in por_tienda))
        resultado["par"] = {t: por_tienda[t][ean_comun] for t in por_tienda}
        ganadora = min(resultado["par"].values(), key=lambda r: num(r["precio"]))
    else:
        resultado["par"] = None
        ganadora = min(resultado["tiendas"].values(), key=ordenador(list(resultado["tiendas"].values())))

    resultado["ganadora"] = ganadora
    precio_hoy = num(ganadora["precio"])
    ean = ganadora["ean"]

    # El veredicto se calcula SOLO contra la historia de PedidosYa. Mezclar
    # fuentes parecia funcionar y era falso: con el precio de hoy de PedidosYa
    # contra una mediana de gondola de SEPA, 10 de 17 productos daban "el mas
    # barato de toda la serie" el primer dia. No eran ofertas, era que PeYa
    # Market esta sistematicamente por debajo de la gondola de las cadenas que
    # publica SEPA. Comparado asi, todo es siempre el minimo historico.
    historia = serie_de(filas, ean, "pedidosya", None, fecha)
    resultado["fuente_historia"] = "PedidosYa"

    # SEPA entra como senal aparte, comparada contra si misma: si el precio de
    # gondola de hoy esta muy por debajo de su propia mediana, el producto entro
    # en ciclo de promocion. Eso es un aviso para ir a mirar, no un veredicto.
    sepa_hoy = serie_de(filas, ean, "sepa", None, fecha_siguiente(fecha))
    sepa_antes = serie_de(filas, ean, "sepa", None, fecha)
    if sepa_hoy and len(sepa_antes) >= MIN_DIAS:
        pct = pct_mas_caros(sepa_antes, min(sepa_hoy))
        if pct >= UMBRAL_BARATO:
            resultado["senal_sepa"] = f"en gondola esta mas barato que el {pct:.0f}% de los dias"

    resultado["dias"] = len(historia)
    if len(historia) < MIN_DIAS:
        resultado["veredicto"] = "SIN HISTORIA"
        resultado["detalle"] = f"{len(historia)} dia(s) de historia, hacen falta {MIN_DIAS}"
        return resultado

    resultado["minimo"] = min(historia)
    resultado["mediana"] = statistics.median(historia)
    resultado["barato_pct"] = pct_mas_caros(historia, precio_hoy)

    if precio_hoy <= resultado["minimo"]:
        resultado["veredicto"] = "COMPRAR"
        resultado["detalle"] = "es el precio mas bajo de toda la serie"
    elif resultado["barato_pct"] >= UMBRAL_BARATO:
        resultado["veredicto"] = "COMPRAR"
        resultado["detalle"] = (f"mas barato que el {resultado['barato_pct']:.0f}% "
                                f"de los dias ({fuente_historia})")
    else:
        resultado["veredicto"] = "ESPERAR"
        resultado["detalle"] = (f"solo mas barato que el {resultado['barato_pct']:.0f}% "
                                f"de los dias; mediana ${resultado['mediana']:,.0f}")
    return resultado


def money_unit(r: dict | None) -> str:
    """Precio del envase mas su precio por unidad.

    Sin el segundo el numero engaña: al ordenar por conveniencia el ganador pasa
    a ser un envase mas grande y mas caro, y la columna parece haber subido de
    precio sin explicacion.
    """
    if not r:
        return "—"
    pu = por_unidad(r)
    if not pu:
        return money(r["precio"])
    return f"{money(r['precio'])}<br><small>{money(pu[1])}/{pu[0]}</small>"


def money(v) -> str:
    n = num(v)
    return f"${n:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".") if n is not None else "-"


def html(fecha, analisis, sin_confirmar, n_filas, n_dias) -> None:
    """Pagina autocontenida, pensada para mirar desde el telefono.

    Sin CSS ni fuentes externas: tiene que abrir igual desde un archivo local,
    desde GitHub Pages o dentro de un mail, sin depender de que cargue nada.
    """
    def fila_html(a):
        item = a["item"]
        if not a["tiendas"]:
            return f'<tr class="vacia"><td>{item["nombre"]}</td><td colspan="3">{a["detalle"]}</td></tr>'
        fuente = a["par"] or a["tiendas"]
        market = next((r for t, r in fuente.items() if "Market" in t), None)
        carre = next((r for t, r in fuente.items() if "Carrefour" in t), None)
        pm = num(market["precio"]) if market else None
        pc = num(carre["precio"]) if carre else None
        gana_m = pm is not None and (pc is None or pm < pc)
        promo = market["promo_tag"] if market and market["promo_tag"] else ""
        chip = f'<span class="promo">{promo}</span>' if promo else ""
        aviso = "" if a["comparable"] or not (pm and pc) else '<span class="aviso">distinto producto</span>'
        estado = a["veredicto"] or ""
        hint = f'<span class="hint">{a["senal_sepa"]}</span>' if a.get("senal_sepa") else ""
        clase = {"COMPRAR": "comprar", "ESPERAR": "esperar"}.get(estado, "gris")
        etiqueta = {"COMPRAR": "COMPRAR", "ESPERAR": "esperar",
                    "SIN HISTORIA": f"faltan {MIN_DIAS - a.get('dias', 0)} d"}.get(estado, "—")
        return (
            f'<tr><td class="prod">{item["nombre"]}{chip}{aviso}</td>'
            f'<td class="{"gana" if gana_m else ""}">{money_unit(market)}</td>'
            f'<td class="{"gana" if pm and pc and not gana_m else ""}">{money_unit(carre)}</td>'
            f'<td><span class="badge {clase}">{etiqueta}</span>{hint}</td></tr>'
        )

    # La pagina es su propio monitor. Si la corrida diaria falla (bloqueo de
    # PerimeterX, notebook apagada, sin internet) el reporte de ayer se queda
    # publicado y parece al dia. Sin este aviso, un dato viejo se lee como dato
    # bueno, que es peor que no tener pagina.
    hoy_iso = date.today().isoformat()
    atraso = (date.today() - date.fromisoformat(fecha)).days
    banner = ""
    if atraso >= 1:
        banner = (f'<section class="stale"><b>Datos de hace {atraso} dia(s).</b> '
                  f'La corrida del {hoy_iso} no llego a actualizar. '
                  f'Revisar <code>data/run-daily.log</code>, o correr '
                  f'<code>py_fetch.py login</code> si PedidosYa pide captcha.</section>')

    comprar = [a for a in analisis if a["veredicto"] == "COMPRAR"]
    destacado = "".join(
        f'<li><b>{a["item"]["nombre"]}</b> — {money(a["ganadora"]["precio"])} '
        f'en {a["ganadora"]["tienda"]}. {a["detalle"]}.</li>' for a in comprar)
    bloque_comprar = (f'<section class="hoy"><h2>Comprar hoy</h2><ul>{destacado}</ul></section>'
                      if comprar else
                      '<section class="hoy vacio"><h2>Nada urgente hoy</h2>'
                      '<p>Ningun producto esta en su franja barata.</p></section>')
    pendientes = "".join(f"<li>{s}</li>" for s in sorted(set(sin_confirmar)))
    bloque_pend = (f'<details><summary>Falta confirmar {len(set(sin_confirmar))} producto(s)</summary>'
                   f'<ul class="pend">{pendientes}</ul></details>' if sin_confirmar else "")

    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Precio radar — {fecha}</title><style>
:root{{--bg:#faf9f7;--card:#fff;--tx:#1a1a1a;--mu:#6b6b6b;--ln:#e5e3df;
--ok:#0f7b3f;--okbg:#e6f4ec;--wait:#8a6d1f;--waitbg:#fdf4dd;--pr:#b3261e}}
@media(prefers-color-scheme:dark){{:root{{--bg:#131313;--card:#1c1c1c;--tx:#ededed;
--mu:#9a9a9a;--ln:#2e2e2e;--ok:#5ed69a;--okbg:#10331f;--wait:#e0c368;--waitbg:#332b12;--pr:#ff8a80}}}}
*{{box-sizing:border-box}}body{{margin:0;padding:16px;background:var(--bg);color:var(--tx);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}}
.wrap{{max-width:760px;margin:0 auto}}h1{{font-size:1.35rem;margin:0 0 2px}}
.fecha{{color:var(--mu);font-size:.85rem;margin-bottom:18px}}
section,details{{background:var(--card);border:1px solid var(--ln);border-radius:14px;
padding:14px 16px;margin-bottom:14px}}h2{{font-size:1rem;margin:0 0 8px}}
.hoy ul{{margin:0;padding-left:18px}}.hoy li{{margin:4px 0}}
.hoy.vacio h2{{color:var(--mu)}}.hoy.vacio p{{margin:0;color:var(--mu);font-size:.9rem}}
.tabla{{padding:0;overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:.9rem}}
th,td{{padding:9px 12px;text-align:right;border-bottom:1px solid var(--ln);white-space:nowrap}}
th:first-child,td:first-child{{text-align:left;white-space:normal;min-width:150px}}
th{{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:var(--mu);font-weight:600}}
tr:last-child td{{border-bottom:0}}.gana{{font-weight:700;color:var(--ok)}}
.vacia td{{color:var(--mu)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.72rem;font-weight:700}}
.comprar{{background:var(--okbg);color:var(--ok)}}.esperar{{background:var(--waitbg);color:var(--wait)}}
.gris{{background:var(--ln);color:var(--mu)}}
.promo{{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:6px;
background:var(--pr);color:#fff;font-size:.68rem;font-weight:700}}
.aviso{{display:block;color:var(--mu);font-size:.72rem}}
.hint{{display:block;color:var(--mu);font-size:.68rem;margin-top:3px;white-space:normal;max-width:150px}}
td small{{color:var(--mu);font-weight:400;font-size:.78rem}}
.stale{{background:#fdf4dd;border-color:#e0c368;color:#6b551a}}
@media(prefers-color-scheme:dark){{.stale{{background:#332b12;border-color:#7a6a2e;color:#e6d9a8}}}}
.stale code{{font-size:.85em;background:rgba(0,0,0,.08);padding:1px 4px;border-radius:4px}}
summary{{cursor:pointer;font-weight:600;font-size:.9rem}}
.pend{{font-size:.8rem;color:var(--mu);padding-left:18px}}
footer{{color:var(--mu);font-size:.78rem;text-align:center;padding:4px 0 20px}}
</style></head><body><div class="wrap">
<h1>Precio radar</h1><div class="fecha">{fecha} · PeYa Market vs Carrefour en PedidosYa</div>
{banner}
{bloque_comprar}
<section class="tabla"><table><thead><tr><th>Producto</th><th>PeYa Market</th>
<th>Carrefour</th><th>Cuando</th></tr></thead><tbody>
{"".join(fila_html(a) for a in analisis)}
</tbody></table></section>
{bloque_pend}
<footer>{n_filas} filas · {n_dias} dia(s) de serie · el veredicto necesita {MIN_DIAS}</footer>
</div></body></html>"""
    HTML.write_text(doc, encoding="utf-8")
    publico = ROOT / "docs" / "index.html"
    if publico.parent.exists():
        publico.write_text(doc, encoding="utf-8")


def main() -> None:
    # La consola de Windows viene en cp1252 y revienta con el signo menos real
    # (U+2212) que usa el reporte. El archivo ya se escribio bien; lo que falla
    # es solo el print, asi que el error seria puro ruido.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    filas = load()
    if not filas:
        raise SystemExit("serie.csv vacio. Corre `python src/store.py py`.")

    fecha = sys.argv[1] if len(sys.argv) > 1 else max(r["fecha"] for r in filas)
    spec = yaml.safe_load((ROOT / "basket.yaml").read_text(encoding="utf-8"))
    analisis = [analizar(filas, item, fecha) for item in spec["items"]]

    lineas = [f"# Precio radar — {fecha}", ""]
    comprar = [a for a in analisis if a["veredicto"] == "COMPRAR"]
    if comprar:
        lineas.append("## Comprar hoy")
        lineas.append("")
        for a in comprar:
            g = a["ganadora"]
            lineas.append(f"- **{a['item']['nombre']}** — {money(g['precio'])} en {g['tienda']}. "
                          f"{a['detalle']}.")
        lineas.append("")

    lineas += ["## Donde esta mas barato hoy", "",
               "| Producto | PeYa Market | Carrefour | Diferencia | Cuando comprar |",
               "|---|---|---|---|---|"]

    sin_confirmar: list[str] = []
    for a in analisis:
        item = a["item"]
        if not a["tiendas"]:
            lineas.append(f"| {item['nombre']} | — | — | — | {a['detalle']} |")
            continue
        # Con `par` las dos columnas son el mismo EAN y la resta significa algo.
        # Sin `par`, cada tienda tiene su producto y se muestra igual, pero
        # avisando que no es una comparacion.
        fuente_par = a["par"] or a["tiendas"]
        market = next((r for t, r in fuente_par.items() if "Market" in t), None)
        carre = next((r for t, r in fuente_par.items() if "Carrefour" in t), None)
        pm, pc = num(market["precio"]) if market else None, num(carre["precio"]) if carre else None
        if pm is not None and pc is not None and a["comparable"]:
            diff = pc - pm
            signo = f"{'PeYa' if diff > 0 else 'Carrefour'} −{money(abs(diff))}" if diff else "iguales"
        elif pm is not None and pc is not None:
            # Marcas distintas en cada tienda: el precio de la caja no dice nada
            # (1 kg contra 500 g), pero el precio por unidad si, siempre que las
            # dos esten medidas en lo mismo.
            um, uc = (market.get("unidad") or ""), (carre.get("unidad") or "")
            ppm, ppc = num(market["precio_por_unidad"]), num(carre["precio_por_unidad"])
            if ppm and ppc and um and um == uc:
                d = ppc - ppm
                lado = "PeYa" if d > 0 else "Carrefour"
                signo = (f"{lado} −{money(abs(d))}/{um} · marcas distintas"
                         if d else f"iguales por {um}")
            else:
                signo = "distinto producto"
        else:
            signo = "solo una tienda"
        veredicto = a["veredicto"] or "—"
        if a["veredicto"] == "SIN HISTORIA":
            veredicto = f"faltan {MIN_DIAS - a['dias']} dias"
        elif a["veredicto"] == "COMPRAR":
            veredicto = f"**COMPRAR** — {a['detalle']}"
        else:
            veredicto = a["detalle"]
        promo = f" ({market['promo_tag']})" if market and market["promo_tag"] else ""
        if a.get("senal_sepa"):
            veredicto += f" · {a['senal_sepa']}"
        lineas.append(f"| {item['nombre']} | {money_unit(market)}{promo} | "
                      f"{money_unit(carre)} | {signo} | {veredicto} |")
        for r in a["tiendas"].values():
            if r["sin_confirmar"]:
                sin_confirmar.append(f"{item['id']} · {r['tienda']} · {r['nombre']} (EAN {r['ean']})")

    if sin_confirmar:
        lineas += ["", "## Falta confirmar el producto", "",
                   "Estos salieron del buscador y todavia no estan en `accepted_eans`, "
                   "asi que la comparacion puede estar mirando otro producto:", ""]
        lineas += [f"- {s}" for s in sorted(set(sin_confirmar))]

    dias_serie = len({r["fecha"] for r in filas})
    lineas += ["", f"_Serie: {len(filas)} filas, {dias_serie} dia(s). "
                   f"El veredicto de 'cuando' necesita {MIN_DIAS}._"]

    texto = "\n".join(lineas)
    SALIDA.write_text(texto, encoding="utf-8")
    html(fecha, analisis, sin_confirmar, len(filas), len({r["fecha"] for r in filas}))
    print(texto)
    print(f"\n-> {SALIDA.relative_to(ROOT)}")
    print(f"-> {HTML.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
