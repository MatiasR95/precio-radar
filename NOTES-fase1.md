# Fase 1 — cambio de enfoque (2026-08-12)

## Que cambia

El universo ya no son los 8.796 EAN comparables de SEPA. Ahora es **lo que
efectivamente se puede comprar en PedidosYa**, y la comparacion es
**PeYa Market vs Carrefour dentro de PedidosYa** (mismo canal, mismo costo de
envio, precios realmente comparables). Ademas cada producto necesita una
**serie historica** para poder decir "hoy esta barato" en vez de solo "hoy esta
mas barato aca que alla".

## PedidosYa no se puede automatizar. Verificado, no supuesto

Tres comprobaciones independientes, todas hoy:

1. **PerimeterX.** Cualquier request que no venga de un navegador real devuelve
   `403` con `px-captcha` (`window._pxAppId = 'PXeT15wiaE'`). Probado con curl
   con User-Agent de Chrome y con un navegador headless: los dos rebotan.
2. **robots.txt.** `Disallow: /v1* /v2* /v3* /mobile/v1* /mobile/v2* /mobile/v3*`.
   `/mobile/v3/shop/list` es justamente el endpoint del catalogo.
3. **No esta en SEPA.** Se listaron las 31 banderas del feed de hoy: INC
   (Carrefour x4), DORINKA (Changomas x5), COTO, Coop. Obrera, DIA, Libertad x3,
   La Anonima/Topsy/Bomba, Toledo, Cencosud (Vea/Disco/Jumbo), Axion, Deheza,
   California, Comodin, Mariano Max, Unicoop, La Agricola, Estacion Lima.
   **Ni PedidosYa ni PeYa Market aparecen.**

Conclusion: los precios de PedidosYa entran por la sesion del navegador de
Matias, no por un crawler.

## La web muestra los mismos precios que la app

Matias lo verifico el 2026-08-12 comparando el mismo producto en los dos lados
con la misma cuenta y la misma direccion. **Los precios coinciden.** La unica
diferencia es cosmetica: la app pone el cartelito "30% OFF" y la web muestra el
precio final pelado, sin avisar que hay descuento.

Esa diferencia no importa para nada, porque el descuento es justamente lo que
calcula la serie historica. "42% por debajo de la mediana de los ultimos 60
dias" es mejor senal que el cartel de ellos, y no depende de que lo pongan.

Consecuencia: **se cae toda la rama movil.** No hace falta emulador de Android,
ni mitmproxy, ni tocar el iPhone (que ademas, al ser iPhone, hubiera sido un
callejon sin salida por el certificate pinning).

## Como entran los precios de PedidosYa

`src/py_fetch.py` — Playwright manejando el **Edge real** de Matias con un
perfil persistente en `data/browser-profile/`.

Por que un navegador y no `requests`: PerimeterX devuelve 403 a todo lo que no
sea un navegador real. Incluido `sitemap.xml`, que ellos mismos publican en su
robots.txt. Probado con curl con User-Agent de Chrome sobre `/sitemap.xml`,
`/online/la-plata` y `/restaurantes/la-plata`: los tres 403.

Por que perfil persistente: la cookie `_px3` que deja PerimeterX despues de una
visita legitima es lo que hace que las corridas siguientes entren sin ser
molestadas. Con un perfil limpio en cada corrida, cada corrida seria un visitante
nuevo y sospechoso.

**El perfil contiene la sesion de PedidosYa: es una credencial, no un artefacto.**
Esta en `.gitignore` junto con los volcados de `discovery-*.json`, que pueden
traer direccion e historial de pedidos mezclados con el catalogo.

Cuando PerimeterX igual desafie (va a pasar cada tanto), el script lo detecta por
el titulo de la pagina, corta y avisa. Matias resuelve un captcha en una ventana
visible y queda andando semanas. Es el patron propone -> revision humana -> sigue
aplicado al unico paso que realmente necesita una persona.

`src/py_capture.js` (snippet de consola) queda como respaldo por si Playwright
falla, pero el camino principal es `py_fetch.py`.

### Sobre parse.bot / Apify (sugerencia de Grok)

`https://api.parse.bot/mcp` existe (devuelve `405` a un GET, o sea acepta POST;
esta detras de Cloudflare). Es viable **como fuente alternativa**, con tres
salvedades: es pago, no esta validado contra PerimeterX (que es el problema
real, y ningun proveedor lo garantiza), y sigue siendo acceso automatizado a los
endpoints que PeYa prohibe en robots.txt — el intermediario no cambia eso.

Decision: **no atar el pipeline a eso**. El snippet y un scraper externo
producen el mismo insumo, asi que la capa de almacenamiento + tendencia +
reporte se construye contra un esquema propio y el metodo de captura queda
enchufable. Si parse.bot resulta funcionar, se agrega como segundo escritor y
no se tira nada de lo hecho.

## La API de PedidosYa (descubierta el 2026-08-12, 172 respuestas capturadas)

Base: `https://www.pedidosya.com.ar/groceries/web/v1`

| Endpoint | Para que |
|---|---|
| `/catalogues/{catalogue}/search?query=&partnerId={vendor}&max=50&offset=0` | encontrar productos |
| `/vendors/{vendor}/products/{id}` | precio autoritativo |
| `/vendors/{vendor}/products?categoryId=&limit=&page=` | listado paginado |
| `/vendors/{vendor}/categories` | arbol de categorias (27 raiz en PeYa Market) |

Tiendas: **163630** PeYa Market La Plata (catalogue 163207) y **555029**
Carrefour Hiper City Bell (catalogue 829303). El vendor y el catalogue son
numeros distintos, no se puede usar uno por el otro.

Estos paths **no** caen bajo el `Disallow` de robots.txt: lo prohibido son
`/v1*`, `/v2*`, `/v3*` y `/mobile/v*`, o sea rutas que *empiezan* con eso.
`/groceries/web/v1/...` no empieza con `/v1`. Los endpoints que si estan
prohibidos (`/v3/shoplist/filters`, `/v1/food-home/v1/vendors`) no hacen falta:
solo servian para descubrir los vendors, y esos ids ya estan fijos en basket.yaml.

### Tres trampas, todas verificadas contra la API real

1. **`ctx.request` de Playwright da 403.** Comparte las cookies pero no los
   headers que arma el cliente JS de PedidosYa. La misma URL, con la pagina ya
   cargada y sin bloqueo, rebota. La solucion es un `fetch` same-origin adentro
   de la pagina (`page.evaluate`): eso devuelve 200.
2. **El `stock` de la busqueda esta desactualizado.** Para las capsulas Starbucks
   la busqueda devolvia `stock: 0` y el detalle `stock: 14`. La busqueda tampoco
   trae `beforePrice`. Por eso el flujo es: buscar para conseguir el id, y pedir
   el detalle para el precio que se guarda.
3. **Dos esquemas distintos para lo mismo.** El detalle y el listado usan
   camelCase con un objeto `pricing` anidado (`price`, `beforePrice`,
   `pricePerMeasurementUnit`); la busqueda usa snake_case y plano (`price`,
   `price_per_measurement_unit`), sin `pricing`.

### El `gtin` es el EAN

PedidosYa publica `"gtin": "08445291786721"` — GTIN-14 con ceros a la izquierda.
Sacando los ceros queda el EAN de SEPA y de las tiendas VTEX. **El join entre
PedidosYa, SEPA y Carrefour/DIA/Disco es exacto por EAN, sin matching por
texto.** Es el hallazgo que mas simplifica el proyecto.

Ademas PedidosYa nombra el producto mejor que las cadenas:
`"Capsulas Starbucks Nespresso Hazelnut 10 Unidades"` dice el sistema en el
nombre, cosa que ni Carrefour ni Disco hacen.

### El descuento viene en la respuesta

`campaigns[].tag` (`"30%"`) y `pricing.beforePrice` estan en la API web. La web
solo esconde el cartel visualmente. Igual se guarda la serie propia: el
`beforePrice` es el ancla que pone PedidosYa, no el precio historico real.

### Primera corrida (2026-08-12)

102 filas, 0 items sin resultado. Capsulas Starbucks Nespresso Hazelnut:
PeYa Market **$10.202,50** (30% off, stock 14) contra Carrefour-en-PY $14.875.
Leche Protein 1 L: PeYa Market $2.989 contra Carrefour $2.999.

**Pendiente de confirmar:** todas las filas de Carrefour volvieron con
`stock: 0`, incluso productos que Carrefour vende. O la tienda estaba cerrada a
esa hora o esa integracion no publica stock. Hasta verlo distinto de cero una
vez, de Carrefour se usa el precio y no el stock.

## La serie y el reporte

`src/store.py` escribe `data/serie.csv`: una fila por (fecha, fuente, tienda,
ean), formato largo. Una tienda nueva es una fila nueva, no una migracion de
esquema. Al ingestar se reemplaza la particion (fecha, fuente) entera, asi que
reintentar despues de un error no duplica el dia — un dia duplicado ensucia la
mediana para siempre y no se nota hasta mucho despues.

`src/report.py` contesta dos preguntas por separado, a proposito:
**donde** (comparacion del dia) se responde con la corrida de hoy; **cuando**
(precio de hoy contra su propia historia) necesita `MIN_DIAS = 10` y por debajo
de eso dice cuantos faltan en vez de inventar una tendencia con tres puntos.
Prioriza la historia de PedidosYa; si no alcanza, usa la de SEPA y lo aclara.

### Cuatro bugs que costaron la sesion, todos del mismo tipo

Los cuatro producian un resultado que *parecia* correcto. Ninguno tiraba error.

1. **La busqueda no aplicaba las reglas de basket.yaml.** Se buscaba por nombre y
   se tomaban los 3 mas baratos. "Rollo de cocina" daba papel de armar Smoking,
   "Suprema de pollo" daba pollo rebozado que la regla `none: [rebozad]` descarta
   explicitamente, y "Yogur natural" daba yogur de frutilla. 14 de 17 filas del
   reporte comparaban el producto equivocado. Ahora se pasan las mismas reglas
   que se usan contra SEPA (`match.matches`).
2. **Comparar el mas barato de cada tienda no es comparar.** Daba yerba Mañanita
   de 1 kg en PeYa contra Mañanita de 500 g en Carrefour y anunciaba $2.411 de
   diferencia. Ahora la resta solo se hace sobre un **EAN presente en las dos
   tiendas**; si no hay ninguno en comun, la celda dice "distinto producto" y no
   se resta nada.
3. **Un 403 se veia igual que "no hay resultados".** `api_get` devolvia `None`
   ante cualquier respuesta no-200, asi que un bloqueo llenaba el reporte de
   "sin resultado" como si los productos no existieran. Ahora distingue por
   status, reintenta con backoff en 401/403/429 y corta la corrida con
   `Bloqueado` en vez de guardar un dia a medias.
4. **Procesos de Edge huerfanos.** Cuando la corrida murio por el bloqueo
   quedaron 9 procesos agarrados al perfil y el arranque siguiente fallo con
   `Opening in existing browser session`. El `ctx.close()` estaba en el camino
   feliz; ahora esta en un `finally`.

### Limite de ritmo

Unas 200 llamadas en pocos minutos (tres corridas completas seguidas mientras se
depuraba) alcanzaron para que PerimeterX bloqueara la sesion entera, hasta la
carga de la home. Se destraba con `login` y un captcha a mano.

La corrida diaria ahora hace ~50 llamadas con 2 s de pausa (`PAUSA_SEGUNDOS`), y
el detalle se pide solo para los EAN confirmados — a los candidatos sin confirmar
les alcanza el precio de la busqueda. **No correr `daily` varias veces seguidas
para probar cosas**: se prueba con `report.py`, que lee de serie.csv y no toca la
red.

## Donde corre cada cosa

| Pieza | Donde | Cada cuanto | Costo |
|---|---|---|---|
| Precios de PedidosYa (`py_fetch.py daily`) | Task Scheduler, notebook de Matias | 1 vez por dia | $0 |
| Snapshot de SEPA + tendencia + reporte | GitHub Actions | 1 vez por dia | 30 corridas/mes contra el techo de ~1500 |

El trabajo de PedidosYa no puede vivir en Actions: necesita una sesion logueada y
persistente, y un runner efimero no tiene ninguna de las dos. Si algun dia se
quiere unificar, un self-hosted runner en el mismo notebook no se factura contra
la cuota (playbook de Actions, palanca 4).

Si el notebook esta apagado un dia, PedidosYa queda con un hueco y SEPA sigue
publicando igual. Se degrada, no se rompe.

Volumen: ~20 productos, una vez por dia, desde un unico cliente logueado. La
misma carga que Matias abriendo la app. Se queda ahi.

## La tendencia

Las capturas de PeYa dependen de que el notebook este prendido, y una serie con
huecos no sirve para decir "hoy esta barato". Por eso la tendencia se arma con
dos senales:

- **Serie densa (diaria, gratis, automatica): SEPA.** El precio de gondola de
  Carrefour se publica todos los dias. No es el precio de PeYa, pero el *ciclo
  de promocion* es el mismo producto y el mismo proveedor: si Nestle pone la caja
  de Starbucks en promo, se ve en SEPA aunque el nivel de precio difiera.
  Sirve como disparador: "esto se movio, anda a mirar PeYa".
- **Serie rala (cuando Matias captura): PedidosYa.** Es la que fija el precio
  real que se paga, y la que confirma o desmiente el disparador.

El feed de SEPA se pisa cada 7 dias, asi que el historico hay que guardarlo
desde hoy. Sin eso no hay tendencia en ningun escenario.

## Productos revisados

### leche-protein — el sachet no existe en la practica

`7790742352101` "Leche ultra descremada La Serenisima Protein sachet 1 lt"
figura en el catalogo de Carrefour pero con `Price: 0` y `AvailableQuantity: 0`.
Es una ficha zombie: vive en los feeds de precio y no se puede comprar. Como en
SEPA aparecia a $2.285 (DIA), se llevaba el primer puesto del ranking siendo el
mas barato justamente por no existir.

Producto real: `7790742358608` "Leche Protein La Serenisima 1 L" botella,
Carrefour $2.999 con stock. El sachet quedo en `rejected_eans`.

### capsulas-starbucks — Nespresso y Dolce Gusto estaban mezcladas

La regla vieja (`all: [starbucks]`, `any: [capsula, nespresso]`) metia los dos
sistemas en la misma bolsa y comparaba cajas de maquinas distintas.

Discriminador confiable (el texto no alcanza, las descripciones no dicen el
sistema): **Nespresso Original = 10 capsulas, caja de 51-57 g (~5,1-5,7 g por
capsula). Dolce Gusto = 12 capsulas, caja de ~120 g (~10 g por capsula).**

El "hazelnut" que vio Matias en PeYa a **$10.202,50** es
`8445291786721` "Capsulas de cafe Starbucks Choco Hazelnut 10 uni", 51 g.
Es **Nespresso** — confirmado por la especificacion del propio Carrefour:
`Unidad de Necesidad = CAFE CAPSULA NESPRESSO`, proveedor Nestle Argentina,
origen Suiza, alta 15/04/2026.

| Fuente | Precio caja 10 |
|---|---|
| PedidosYa | $10.202,50 |
| Disco / Jumbo | $17.100 |
| Carrefour | $17.589 |

40% de diferencia. Este es el caso testigo del proyecto.

Ojo con el homonimo: `7891000454466` "Capsulas Starbucks Hazelnut 123 gr" es
**Dolce Gusto** (123 g / 12 capsulas), sin stock en ningun lado. Esta en
`rejected_eans` para que no se cuele por el nombre.

Quedaron 9 EAN en `revisar_eans`: los de `Price 0` (fichas duplicadas o dadas de
baja) y el "House Blend 18 uni", que no encaja en el formato de ninguno de los
dos sistemas.

## Pendiente

- Primera captura de PeYa con `src/py_capture.js` para conocer el esquema real
  de la respuesta y escribir el parser (`src/py_parse.py`).
- Guardado diario del snapshot de SEPA (solo las banderas y los EAN de la
  canasta: son ~20 productos, no 300 MB por dia).
- Reporte: para cada item, precio PeYa Market vs Carrefour-en-PeYa, mas percentil
  del precio de hoy contra los ultimos 60 dias.
- Confirmar en PeYa cuales de los 9 `revisar_eans` existen de verdad; los que no,
  se descartan solos por la regla nueva.
