"""Lee precios de PedidosYa con un Edge real y un perfil persistente.

Por que un navegador y no requests: PedidosYa esta detras de PerimeterX. Todo lo
que no sea un navegador real devuelve 403, incluso el sitemap.xml que ellos
mismos publican en robots.txt. Verificado el 2026-08-12.

Por que un perfil persistente: la cookie `_px3` que PerimeterX deja despues de
una visita legitima es lo que hace que las corridas siguientes pasen sin
molestar. Si cada corrida arrancara con un perfil limpio, cada corrida seria un
visitante nuevo y sospechoso. El perfil vive en data/browser-profile/ y **tiene
la sesion de PedidosYa adentro: nunca se commitea** (ya esta en .gitignore).

Tres modos:

    python src/py_fetch.py login
        Abre Edge visible con el perfil del proyecto. Logueate en PedidosYa,
        elegi la direccion de La Plata, y resolve el captcha si aparece. Se hace
        una sola vez (y de nuevo si algun dia caduca la sesion).

    python src/py_fetch.py discover
        Abre Edge visible y graba todas las respuestas JSON mientras navegas
        PeYa Market y Carrefour. Sirve para conocer el esquema real de la API y
        recien despues escribir el parser. Tambien se hace una sola vez.

    python src/py_fetch.py daily
        Modo desatendido, el que corre por Task Scheduler. Busca cada item de
        basket.yaml en las dos tiendas, pide el detalle de cada candidato y
        escribe data/py/py-YYYY-MM-DD.json. Abre una ventana unos segundos y se
        cierra sola.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from urllib.parse import urlencode

from playwright.sync_api import Response, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "data" / "browser-profile"
OUT_DIR = ROOT / "data" / "py"

HOME = "https://www.pedidosya.com.ar/"
LA_PLATA = (-34.9214, -57.9544)  # mismo centro que usa src/sepa.py

# Solo interesa el trafico de catalogo. Analytics, mapas, imagenes y tracking son
# ruido: engordan el volcado sin aportar un solo precio.
INTERESTING = ("product", "catalog", "search", "menu", "item", "categor",
               "shop", "store", "vendor", "grocer", "listing", "price")
IGNORE = ("analytics", "segment", "datadog", "sentry", "newrelic", "hotjar",
          "braze", "amplitude", "googletag", "doubleclick", "facebook", "clarity")

MAX_CAPTURE_BYTES = 40 * 1024 * 1024


def wanted(url: str) -> bool:
    low = url.lower()
    if any(bad in low for bad in IGNORE):
        return False
    return any(good in low for good in INTERESTING)


def is_blocked(page) -> bool:
    """True si PerimeterX interpuso su pantalla en lugar de la pagina real."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        return False
    return "acceso" in title and "denegado" in title or "access to this page" in title


def soltar_perfil() -> int:
    """Cierra los Edge que quedaron agarrados al perfil del proyecto.

    Cuando una corrida muere de golpe, sus procesos siguen vivos y el arranque
    siguiente falla con "Opening in existing browser session". El `finally` de
    cmd_daily cubre las salidas ordenadas; esto cubre las que no lo son.

    El filtro por linea de comando es lo unico que separa estos procesos del
    Edge personal de Matias, que no se toca. Sin ese filtro esto le cerraria el
    navegador con todas sus pestañas.
    """
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{PROFILE.name}*' -and "
        f"$_.CommandLine -like '*precio-radar*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; 1 } | "
        "Measure-Object | Select-Object -ExpandProperty Count"
    )
    try:
        salida = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                capture_output=True, text=True, timeout=60)
        n = int((salida.stdout or "0").strip() or 0)
    except Exception:
        return 0
    for lock in PROFILE.glob("Singleton*"):
        try:
            lock.unlink()
        except OSError:
            pass
    if n:
        time.sleep(2)
    return n


def open_browser(pw, headless: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    try:
        return _launch(pw, headless)
    except Exception as e:
        if "existing browser session" not in str(e):
            raise
        n = soltar_perfil()
        print(f"Perfil tomado por {n} proceso(s) huerfano(s); cerrados. Reintento.")
        return _launch(pw, headless)


def _launch(pw, headless: bool):
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="msedge",
        headless=headless,
        # Ventana maximizada real en vez de un viewport fijo: el modal de
        # direccion de PedidosYa mete un mapa y el boton de confirmar debajo, y
        # con 950 px de alto el boton queda cortado (el modal no scrollea).
        no_viewport=True,
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
        # Sin permiso de geolocalizacion el modal de direccion nunca fija el pin
        # y el boton de confirmar queda muerto. Playwright lo deniega por defecto.
        permissions=["geolocation"],
        geolocation={"latitude": LA_PLATA[0], "longitude": LA_PLATA[1]},
        # Playwright arranca Chromium con --enable-automation, que pone al
        # navegador en modo "soy un robot" a la vista de cualquier script de la
        # pagina. Se saca porque esta es una sesion real y logueada de Matias, no
        # para disfrazar trafico: la cookie de PerimeterX y el login siguen siendo
        # los de siempre.
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
    )


# Se espera a que Matias cierre la ventana, no a que apriete Enter: asi el script
# puede correr lanzado en segundo plano (sin stdin) y la unica interfaz es el
# navegador que ya tiene delante.
WAIT_MINUTES = 45


def wait_until_closed(ctx) -> None:
    print(f"\n>>> Cuando termines, CERRA LA VENTANA DE EDGE. (limite {WAIT_MINUTES} min)")
    try:
        ctx.wait_for_event("close", timeout=WAIT_MINUTES * 60_000)
    except Exception:
        print("Se acabo el tiempo de espera; guardo lo que haya.")


def cmd_login() -> None:
    with sync_playwright() as pw:
        ctx = open_browser(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
        print("\nEdge abierto con el perfil del proyecto.")
        print("  1. Logueate en PedidosYa.")
        print("  2. Elegi la direccion de La Plata.")
        print("  3. Entra una vez a PeYa Market y una vez a Carrefour.")
        print("  4. Si aparece un captcha, resolvelo vos (yo no lo toco).")
        wait_until_closed(ctx)
    print(f"Perfil guardado en {PROFILE.relative_to(ROOT)}")


def cmd_discover() -> None:
    captures: list[dict] = []
    total = 0

    def on_response(res: Response) -> None:
        nonlocal total
        if total >= MAX_CAPTURE_BYTES or not wanted(res.url):
            return
        ctype = (res.headers.get("content-type") or "").lower()
        if "json" not in ctype:
            return
        try:
            body = res.text()
        except Exception:
            return  # respuesta ya descartada por el navegador
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return
        total += len(body)
        captures.append({
            "url": res.url,
            "status": res.status,
            "ts": datetime.now(timezone.utc).isoformat(),
            "body": parsed,
        })

    # El HTML tambien sirve: si el precio viene renderizado en el servidor y no
    # por API, esta ahi y en ninguna respuesta JSON. Se guarda en cada carga
    # porque al cerrar la ventana la pagina ya no se puede leer.
    pages_html: dict[str, str] = {}

    def on_load(page) -> None:
        try:
            pages_html[page.url] = page.content()[:1_000_000]
        except Exception:
            pass  # navegacion en curso: la proxima carga lo agarra

    with sync_playwright() as pw:
        ctx = open_browser(pw, headless=False)
        ctx.on("response", on_response)
        ctx.on("page", lambda pg: pg.on("load", lambda: on_load(pg)))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("load", lambda: on_load(page))
        page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
        if is_blocked(page):
            print("PerimeterX interpuso su pantalla. Resolve el captcha en la ventana.")
        print("\nGrabando. Navega PeYa Market y Carrefour, y busca los productos")
        print("de la canasta (empeza por las capsulas Starbucks Choco Hazelnut).")
        on_load(page)
        wait_until_closed(ctx)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    out = OUT_DIR / f"discovery-{stamp}.json"
    out.write_text(json.dumps({
        "schema": "py-discovery/2",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "count": len(captures),
        "captures": captures,
        "pages_html": pages_html,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"\n{len(captures)} respuestas JSON, {total/1e6:.1f} MB")
    print(f"{len(pages_html)} paginas HTML guardadas")
    print(f"-> {out.relative_to(ROOT)}")
    if not captures:
        print("Cero respuestas: o el precio viene en el HTML, o los filtros de URL")
        print("no pegaron. El HTML quedo guardado igual, se puede mirar ahi.")


# --- modo diario -----------------------------------------------------------

API = "/groceries/web/v1"


class Bloqueado(Exception):
    """PedidosYa dejo de responder 200: cortar la corrida, no seguir a ciegas."""


# Pausa entre llamadas. Sin esto la primera corrida completa (~68 pedidos casi
# instantaneos) hizo que a partir del segundo pedido todo volviera 403. Un
# reporte que dice "sin resultado" cuando en realidad lo estan bloqueando es
# peor que uno que falla: parece que el producto no existe.
PAUSA_SEGUNDOS = 2.0
REINTENTOS = 3


def api_get(page, path: str, params: dict | None = None):
    """Pide un endpoint de PedidosYa desde adentro de la propia pagina.

    No se puede usar el APIRequestContext de Playwright: comparte las cookies
    pero no los headers que arma el cliente JS de PedidosYa, y la API devuelve
    403 (probado el 2026-08-12: la pagina carga bien y la misma URL por
    `ctx.request` rebota). Con un fetch same-origin adentro de la pagina, en
    cambio, responde 200.

    Distingue "no hay resultados" de "me estan bloqueando". Confundirlos fue el
    bug que dejo un reporte entero lleno de falsos "sin resultado".
    """
    url = path + ("?" + urlencode(params) if params else "")
    espera = PAUSA_SEGUNDOS
    for intento in range(REINTENTOS):
        time.sleep(espera)
        res = page.evaluate(
            """async (u) => {
                const r = await fetch(u, {credentials: 'include'});
                let body = null;
                try { body = await r.json(); } catch { body = null; }
                return {status: r.status, body: body};
            }""",
            url,
        )
        if res["status"] == 200:
            return res["body"]
        if res["status"] in (401, 403, 429):
            espera *= 3  # backoff: si es un limite de ritmo, insistir igual lo empeora
            print(f"  HTTP {res['status']}, reintento {intento + 1}/{REINTENTOS} en {espera:.0f}s")
            continue
        return None  # 404 y compania: el producto no esta, no es bloqueo
    raise Bloqueado(f"HTTP persistente en {path}")


def norm_gtin(gtin: str | None) -> str:
    """PedidosYa publica el EAN como GTIN-14 con ceros a la izquierda.

    '08445291786721' es el mismo producto que el 8445291786721 de SEPA y de las
    tiendas VTEX. Sin normalizar, el join por EAN no encuentra nada.
    """
    return (gtin or "").lstrip("0")


def search(page, catalogue: int, vendor: int, query: str) -> list[dict]:
    body = api_get(page, f"{API}/catalogues/{catalogue}/search",
                   {"query": query, "partnerId": str(vendor),
                    "max": "50", "offset": "0", "sort": "default"})
    return (body or {}).get("data") or []


def product_detail(page, vendor: int, product_id) -> dict | None:
    """El detalle es la fuente autoritativa del precio.

    La busqueda trae el precio con descuento ya aplicado, pero su `stock` viene
    desactualizado (devolvia 0 para las capsulas Starbucks que en el detalle
    tenian 14) y no trae `beforePrice`. Para la serie historica se usa el
    detalle; la busqueda solo sirve para encontrar el id.
    """
    body = api_get(page, f"{API}/vendors/{vendor}/products/{product_id}")
    if isinstance(body, list):
        return body[0] if body else None
    return body


def extract(item: dict, vendor: int) -> dict:
    """Aplana un producto del detalle a la fila que se guarda en la serie."""
    pricing = item.get("pricing") or {}
    size = item.get("size") or {}
    campaigns = item.get("campaigns") or []
    return {
        "vendor": vendor,
        "product_id": str(item.get("id") or ""),
        "ean": norm_gtin(item.get("gtin")),
        "nombre": item.get("name"),
        "marca": item.get("defaultBrandName"),
        "precio": pricing.get("price"),
        "precio_antes": pricing.get("beforePrice"),
        "precio_por_unidad": pricing.get("pricePerMeasurementUnit"),
        "unidad": (item.get("size") or {}).get("unit"),
        "contenido": size.get("content"),
        "stock": item.get("stock"),
        "habilitado": (item.get("status") or {}).get("enabled"),
        "promo_tag": campaigns[0].get("tag") if campaigns else None,
    }


def cmd_daily() -> None:
    import yaml

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from match import matches, norm  # mismas reglas que se usan contra SEPA

    spec = yaml.safe_load((ROOT / "basket.yaml").read_text(encoding="utf-8"))
    vendors = spec["meta"]["pedidosya"]["vendors"]
    items = spec["items"]

    filas: list[dict] = []
    faltantes: list[str] = []

    with sync_playwright() as pw:
        # Headed a proposito: headless es la senal mas barata que tiene
        # PerimeterX para bloquear, y probado a mano devuelve "Just a moment...".
        # La ventana aparece unos segundos y se cierra sola.
        ctx = open_browser(pw, headless=False)
        # finally y no un close al final de cada camino: cuando la corrida murio
        # por el bloqueo de PerimeterX quedaron 9 procesos de Edge agarrados al
        # perfil, y el arranque siguiente fallo con "Opening in existing browser
        # session". Cualquier salida tiene que soltar el perfil.
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
            if is_blocked(page):
                raise SystemExit(
                    "PerimeterX bloqueo la corrida. Corre `python src/py_fetch.py login`,\n"
                    "resolve el captcha a mano y volve a intentar."
                )
            for item in items:
                aceptados = {str(e) for e in (item.get("accepted_eans") or [])}
                query = item.get("py_query") or item["nombre"]
                for v in vendors:
                    encontrados = search(page, v["catalogue"], v["id"], query)
                    # Con accepted_eans se resuelve por EAN, que es exacto. Sin lista
                    # todavia confirmada, se deja el candidato mas barato para que
                    # Matias lo revise; no se congela nada solo.
                    elegidos = [r for r in encontrados if norm_gtin(r.get("gtin")) in aceptados]
                    revisar = not elegidos and not aceptados
                    if revisar:
                        # El buscador de PedidosYa es generoso: para "Rollo de cocina"
                        # devuelve papel de armar, y para "Suprema de pollo" devuelve
                        # pollo rebozado que la regla `none` descarta explicitamente.
                        # Sin pasar las reglas de basket.yaml, quedarse con el mas
                        # barato es quedarse con el producto equivocado casi siempre.
                        candidatos = [r for r in encontrados
                                      if r.get("price") and matches(norm(str(r.get("name") or "")), item)]
                        elegidos = sorted(candidatos, key=lambda r: r["price"])[:3]
                    if not elegidos:
                        faltantes.append(f"{item['id']} @ {v['nombre']}")
                        continue
                    for r in elegidos:
                        # El detalle solo para los confirmados por EAN: son los que
                        # entran a la serie historica y necesitan `beforePrice` y el
                        # stock bueno. Para los candidatos a revisar alcanza el precio
                        # de la busqueda, y asi la corrida hace la mitad de pedidos
                        # (que es lo que disparo el bloqueo de PerimeterX).
                        detalle = None if revisar else product_detail(page, v["id"], r.get("id"))
                        fila = extract(detalle, v["id"]) if detalle else {
                            "vendor": v["id"], "product_id": str(r.get("id")),
                            "ean": norm_gtin(r.get("gtin")), "nombre": r.get("name"),
                            "precio": r.get("price"),
                            "precio_por_unidad": r.get("price_per_measurement_unit"),
                            # Sin la unidad, comparar "por unidad" entre tiendas
                            # podria terminar restando $/kg contra $/un.
                            "unidad": (r.get("measurement_unit") or {}).get("short_name"),
                        }
                        fila["item"] = item["id"]
                        fila["tienda"] = v["nombre"]
                        fila["sin_confirmar"] = revisar
                        filas.append(fila)
        except Bloqueado as e:
            raise SystemExit(
                f"PedidosYa corto la corrida ({e}).\n"
                f"Se juntaron {len(filas)} filas antes del corte; no se guarda nada\n"
                "para no dejar un dia a medias en la serie. Proba de nuevo mas tarde,\n"
                "o corre `python src/py_fetch.py login` si el bloqueo persiste."
            )
        finally:
            ctx.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"py-{date.today().isoformat()}.json"
    out.write_text(json.dumps({
        "schema": "py-daily/1",
        "fecha": date.today().isoformat(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "filas": filas,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{len(filas)} filas de precio -> {out.relative_to(ROOT)}")
    if faltantes:
        print(f"{len(faltantes)} sin resultado:")
        for f in faltantes:
            print("  -", f)


COMMANDS = {"login": cmd_login, "discover": cmd_discover, "daily": cmd_daily}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        raise SystemExit(__doc__)
    COMMANDS[cmd]()
