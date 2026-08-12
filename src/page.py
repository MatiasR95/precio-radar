"""La pagina HTML del reporte. Separada de report.py: ahi vive el calculo, aca
como se ve.

Idea de diseno: no es un dashboard, es una **etiqueta de gondola**. En el ticket
de estante manda el numero grande y abajo, en chico y encajonado, va el precio
por unidad que exige la ley de gondolas. Esta pagina tiene exactamente esos dos
datos por producto y por tienda, asi que copia esa forma en vez de inventar
tarjetas genericas.

Consecuencias concretas:
  - Toda cifra va en monoespaciada con `tabular-nums`, para que las comas
    alineen entre columnas. El texto va en la sans del sistema.
  - Dos senales de color y nada mas: verde para la tienda que gana, ambar para
    el flash de promocion. Sin degrades.
  - Una sola animacion: la entrada escalonada de los tickets al cargar.

Sin CSS ni fuentes externas: la pagina tiene que abrir igual desde un archivo
local, desde GitHub Pages o dentro de un mail.
"""

from __future__ import annotations

CSS = """
:root{
  --papel:#f1f2f4; --tarjeta:#fff; --tinta:#17181c; --tenue:#6a6f78;
  --linea:#dcdee3; --verde:#0b6b3a; --verde-piso:#e3f1e9;
  --ambar:#ffd21e; --alerta:#8a6d1f; --alerta-piso:#fdf4dd; --alerta-linea:#e0c368;
  --gris-piso:#e4e6ea; --gris-tinta:#4d525a;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --papel:#101114; --tarjeta:#191b1f; --tinta:#eceef2; --tenue:#8d939d;
    --linea:#272a30; --verde:#4fd18b; --verde-piso:#11301f;
    --alerta:#e0c368; --alerta-piso:#2c2512; --alerta-linea:#6d5d28;
    --gris-piso:#23262c; --gris-tinta:#a7adb7;
  }
}
*{box-sizing:border-box}
body{margin:0;padding:20px 16px 40px;background:var(--papel);color:var(--tinta);
  font-family:var(--sans);font-size:16px;line-height:1.45;-webkit-font-smoothing:antialiased}
.wrap{max-width:920px;margin:0 auto}

header{margin-bottom:22px}
h1{font-size:1.05rem;font-weight:650;letter-spacing:.14em;text-transform:uppercase;margin:0}
.sub{font-family:var(--mono);font-size:.78rem;color:var(--tenue);margin-top:5px;
  font-variant-numeric:tabular-nums}

.stale{background:var(--alerta-piso);border:1px solid var(--alerta-linea);
  color:var(--alerta);border-radius:10px;padding:12px 14px;margin-bottom:20px;font-size:.86rem}
.stale code{font-family:var(--mono);font-size:.9em}

.hero{border-top:2px solid var(--tinta);padding-top:12px;margin-bottom:26px}
.hero h2{font-size:.72rem;letter-spacing:.13em;text-transform:uppercase;
  color:var(--tenue);margin:0 0 10px;font-weight:600}
.hero ul{margin:0;padding:0;list-style:none}
.hero li{padding:7px 0;border-bottom:1px solid var(--linea);font-size:.92rem}
.hero li:last-child{border-bottom:0}
.hero b{font-weight:640}
.hero .donde{font-family:var(--mono);color:var(--verde);font-size:.86rem;
  font-variant-numeric:tabular-nums}
.hero .quieto{color:var(--tenue);font-size:.9rem;margin:0}

.tickets{display:grid;gap:12px;grid-template-columns:1fr}
@media (min-width:680px){.tickets{grid-template-columns:1fr 1fr}}
.ticket{background:var(--tarjeta);border:1px solid var(--linea);border-radius:12px;
  padding:14px 15px 12px;display:flex;flex-direction:column;gap:11px}
.nombre{font-size:.82rem;font-weight:600;line-height:1.3;display:flex;
  align-items:flex-start;gap:8px;justify-content:space-between}
.flash{font-family:var(--mono);font-size:.7rem;font-weight:700;background:var(--ambar);
  color:#17181c;border-radius:4px;padding:2px 6px;white-space:nowrap;flex-shrink:0}

.duo{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.lado{min-width:0}
.tienda{font-size:.66rem;letter-spacing:.09em;text-transform:uppercase;color:var(--tenue);
  margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.precio{font-family:var(--mono);font-size:1.18rem;font-weight:600;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em;line-height:1.15}
.lado.gana .precio{color:var(--verde)}
.lado.gana .precio::after{content:"";display:block;height:3px;width:2.1em;margin-top:5px;
  background:var(--verde);border-radius:2px}
.unit{display:inline-block;font-family:var(--mono);font-size:.68rem;color:var(--tenue);
  border:1px solid var(--linea);border-radius:3px;padding:1px 4px;margin-top:6px;
  font-variant-numeric:tabular-nums}
.vacio{font-family:var(--mono);font-size:1.05rem;color:var(--tenue)}

.pie{border-top:1px dashed var(--linea);padding-top:9px;display:flex;flex-wrap:wrap;
  gap:6px 10px;align-items:center}
.badge{font-size:.68rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:3px 8px;border-radius:999px}
.b-comprar{background:var(--verde-piso);color:var(--verde)}
.b-esperar{background:var(--alerta-piso);color:var(--alerta)}
/* El gris tiene su propio par de colores y no reusa --tenue sobre --linea:
   asi daba 3.75:1, por debajo del 4.5 que pide WCAG AA para texto chico. */
.b-gris{background:var(--gris-piso);color:var(--gris-tinta)}
.nota{font-size:.74rem;color:var(--tenue);flex:1;min-width:120px}
.dif{font-family:var(--mono);font-size:.72rem;color:var(--tenue);
  font-variant-numeric:tabular-nums}

details{margin-top:24px;border-top:2px solid var(--tinta);padding-top:12px}
/* padding vertical para llegar a los 44px de area tactil: con el tamano de
   letra solo, el desplegable medía 17px de alto y era imposible de acertar. */
summary{cursor:pointer;font-size:.72rem;letter-spacing:.13em;text-transform:uppercase;
  color:var(--tenue);font-weight:600;padding:14px 0;margin:-14px 0 0}
details p{font-size:.8rem;color:var(--tenue);max-width:60ch}
details code{font-family:var(--mono);font-size:.9em}
.pend{list-style:none;padding:0;margin:10px 0 0;font-size:.76rem}
.pend li{padding:6px 0;border-bottom:1px solid var(--linea);font-family:var(--mono);
  color:var(--tenue);word-break:break-word}

footer{margin-top:26px;font-family:var(--mono);font-size:.7rem;color:var(--tenue);
  text-align:center;font-variant-numeric:tabular-nums}

a:focus-visible,summary:focus-visible{outline:2px solid var(--verde);outline-offset:3px}

/* Una sola animacion en toda la pagina: la entrada escalonada al cargar. */
@media (prefers-reduced-motion:no-preference){
  .ticket{animation:sube .34s cubic-bezier(.22,.9,.3,1) both;
    animation-delay:calc(var(--i) * 40ms)}
  @keyframes sube{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
}
"""


def corta(tienda: str) -> str:
    return "PeYa Market" if "Market" in tienda else "Carrefour"


def construir(fecha, analisis, sin_confirmar, n_filas, n_dias, ctx) -> str:
    """Arma el documento. `ctx` trae los helpers de report.py.

    Se pasan como parametro y no se importan para que page.py no dependa de
    report.py: report ya importa page, y al reves seria circular.
    """
    money, por_unidad, num, min_dias = (
        ctx["money"], ctx["por_unidad"], ctx["num"], ctx["min_dias"])
    atraso, hoy_iso = ctx["atraso"], ctx["hoy_iso"]

    banner = ""
    if atraso >= 1:
        # La pagina es su propio monitor: si la corrida falla, el reporte de ayer
        # queda publicado y parece al dia. Un dato viejo leido como bueno es peor
        # que no tener pagina.
        banner = (f'<div class="stale"><b>Datos de hace {atraso} día(s).</b> '
                  f'La corrida del {hoy_iso} no actualizó. Mirá '
                  f'<code>data/run-daily.log</code>, o corré '
                  f'<code>py_fetch.py login</code> si PedidosYa pide captcha.</div>')

    def lado(r, gana):
        if not r:
            return ('<div class="lado"><div class="tienda">—</div>'
                    '<div class="vacio">sin dato</div></div>')
        pu = por_unidad(r)
        unit = f'<span class="unit">{money(pu[1])}/{pu[0]}</span>' if pu else ""
        clase = " gana" if gana else ""
        return (f'<div class="lado{clase}"><div class="tienda">{corta(r["tienda"])}</div>'
                f'<div class="precio">{money(r["precio"])}</div>{unit}</div>')

    def ticket(a, i):
        item = a["item"]
        fuente = a["par"] or a["tiendas"]
        market = next((r for t, r in fuente.items() if "Market" in t), None)
        carre = next((r for t, r in fuente.items() if "Carrefour" in t), None)
        pm = num(market["precio"]) if market else None
        pc = num(carre["precio"]) if carre else None
        gana_m = pm is not None and (pc is None or pm < pc)

        promo = market["promo_tag"] if market and market["promo_tag"] else ""
        flash = f'<span class="flash">{promo}</span>' if promo else ""

        clase, etiqueta = {
            "COMPRAR": ("b-comprar", "comprar"),
            "ESPERAR": ("b-esperar", "esperar"),
            "SIN HISTORIA": ("b-gris", f"faltan {min_dias - a.get('dias', 0)} d"),
        }.get(a["veredicto"] or "", ("b-gris", "—"))

        notas = []
        if not a["tiendas"]:
            notas.append(a["detalle"])
        elif pm and pc and not a["comparable"]:
            notas.append("cada tienda trae otra marca")
        if a.get("senal_sepa"):
            notas.append(a["senal_sepa"])
        nota = f'<span class="nota">{" · ".join(notas)}</span>' if notas else ""

        dif = ""
        if pm is not None and pc is not None and a["comparable"] and pm != pc:
            lado_gana = "PeYa" if pc > pm else "Carrefour"
            dif = f'<span class="dif">{lado_gana} −{money(abs(pc - pm))}</span>'

        return (f'<article class="ticket" style="--i:{i}">'
                f'<div class="nombre"><span>{item["nombre"]}</span>{flash}</div>'
                f'<div class="duo">{lado(market, gana_m and pm is not None)}'
                f'{lado(carre, pc is not None and not gana_m)}</div>'
                f'<div class="pie"><span class="badge {clase}">{etiqueta}</span>'
                f'{dif}{nota}</div></article>')

    comprar = [a for a in analisis if a["veredicto"] == "COMPRAR"]
    if comprar:
        filas = "".join(
            f'<li><b>{a["item"]["nombre"]}</b> — '
            f'<span class="donde">{money(a["ganadora"]["precio"])}</span> en '
            f'{corta(a["ganadora"]["tienda"])}. {a["detalle"]}.</li>' for a in comprar)
        hero = f'<section class="hero"><h2>Comprar hoy</h2><ul>{filas}</ul></section>'
    else:
        hero = ('<section class="hero"><h2>Comprar hoy</h2>'
                '<p class="quieto">Ningún producto está en su franja barata. '
                'Nada que apurar.</p></section>')

    bloque_pend = ""
    if sin_confirmar:
        pendientes = "".join(f"<li>{s}</li>" for s in sorted(set(sin_confirmar)))
        bloque_pend = (
            f'<details><summary>Por confirmar · {len(set(sin_confirmar))}</summary>'
            f'<p>Salieron del buscador y todavía no están en <code>accepted_eans</code>. '
            f'Se siguen igual, pero la comparación puede estar mirando otro producto.</p>'
            f'<ul class="pend">{pendientes}</ul></details>')

    tickets = "".join(ticket(a, i) for i, a in enumerate(analisis))
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Precio radar · {fecha}</title><style>{CSS}</style></head><body>'
        '<div class="wrap"><header><h1>Precio radar</h1>'
        f'<div class="sub">{fecha} · PeYa Market vs Carrefour en PedidosYa</div></header>'
        f'{banner}{hero}<div class="tickets">{tickets}</div>{bloque_pend}'
        f'<footer>{n_filas} filas · {n_dias} día(s) de serie · '
        f'el veredicto necesita {min_dias}</footer></div></body></html>'
    )
