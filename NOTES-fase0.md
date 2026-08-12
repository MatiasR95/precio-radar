# Fase 0 — hallazgos (2026-08-11)

Todo lo de abajo esta verificado corriendo codigo contra los datos reales de hoy,
no inferido de documentacion.

## El feed SEPA

- ZIP diario: **301 MB**, se descarga en **~10 s**. Se publica uno por dia de semana
  y se pisa cada 7 dias, asi que el historico hay que guardarlo nosotros desde el
  primer dia.
- Estructura: ZIP -> un ZIP por comercio -> `comercio.csv`, `sucursales.csv`,
  `productos.csv`, separados por `|`.
- Columnas de precio confirmadas: `productos_precio_lista`,
  `productos_precio_unitario_promo1` + `productos_leyenda_promo1`, y el par promo2.

## Sucursales cerca de La Plata (radio 25 km): 40

| bandera | id | sucursales | mas cercana |
|---|---|---|---|
| Supermercados DIA | 15.1 | 20 | 0.8 km |
| DEHEZA (kiosco/estacion) | 3.1 | 5 | 1.0 km |
| Vea | 9.1 | 4 | 0.5 km |
| Disco | 9.2 | 3 | 1.3 km |
| Carrefour Market | 10.2 | 2 | 0.5 km |
| Cooperativa Obrera | 13.1 | 1 | 1.0 km |
| COTO | 12.1 | 1 | 1.1 km |
| Carrefour Hipermercado | 10.1 | 1 | 4.9 km |
| HiperChangomas | 11.5 | 1 | 5.2 km |
| Carrefour Express | 10.3 | 1 | 13.6 km |
| Axion Energy | 23.1 | 1 | 23.3 km |

**No hay en La Plata**: Jumbo, Toledo (es de Mar del Plata), La Anonima, Nini,
Libertad, Comodin. Toledo y Nini aparecen en las promos de Cuenta DNI pero no
tienen sucursal aca, asi que esas promos no aplican.

Catalogo de esas 40 sucursales: **195.491 filas de precio, 52.577 EAN distintos**.
De esos, **8.796 EAN los publican 3 o mas banderas** — ese es el universo real
sobre el que se puede comparar. Solo 2 productos los publican las 11 banderas.

EAN publicados por bandera: HiperChangomas 27.940, Carrefour Hiper 22.695,
Carrefour Market 8.484, COTO 7.658, Disco 7.407, Coop. Obrera 6.069, Vea 5.835,
**DIA solo 4.029**. O sea: DIA tiene 20 sucursales cerca pero informa el catalogo
mas chico de las cadenas grandes.

## Trampas del feed (ya manejadas en `src/sepa.py`)

1. **Filtrar por nombre de localidad pierde datos.** DIA publica sus 983 sucursales
   con localidad `BUENOS AIRES`; filtrando por texto daban **0** sucursales en La
   Plata cuando en realidad tiene 20. Hay que filtrar por lat/lon.
2. **Un `id_comercio` agrupa varias banderas.** Cencosud = Vea/Disco/Jumbo,
   INC = Carrefour Hipermercado/Maxi/Express/Market, DORINKA = ChangoMas.
   Agrupar por `(id_comercio, id_bandera)` o se mezclan cadenas distintas.
3. **El EAN no siempre esta en `productos_ean`.** DEHEZA publica el codigo de
   barras en `id_producto` y un `1` en `productos_ean`. Se resuelve mirando ambos.
4. **Hay ZIPs de comercio vacios** (2 hoy) y **filas corruptas** (140 en sucursales,
   34 en productos; Comodin manda saltos de linea dentro de los campos). Se
   descartan por fila y se cuentan, nunca se aborta el archivo.
5. **Hay precios basura**: un queso Finlandia a `$0`, caramelos a `$50`. Sin un
   filtro de cordura el ranking de "mayor diferencia de precio" queda lleno de
   errores de carga en vez de ofertas reales.

## El join entre fuentes funciona

Probado en vivo: EAN de SEPA -> `fq=alternateIds_Ean:` de VTEX.

| EAN | Carrefour | DIA | Disco |
|---|---|---|---|
| Coca-Cola 2.25 L | $5.800 | $5.800 | $5.800 |
| Powerade manzana 500 ml | $2.200 | $2.200 | $2.300 |
| Cepita multifruta 200 ml | $1.250 | $1.300 | sin resultado |

Dos cosas para el pipeline:

- **`ListPrice` de Disco no sirve**: devuelve $479.339 para una Coca de $5.800.
  Usar siempre `Price`, y no calcular el descuento como `1 - Price/ListPrice`.
- **La cobertura por tienda es despareja** (Disco no tiene el Cepita). "Sin dato"
  es un resultado normal y frecuente, no un error.

## Pendiente

- Falta pasar `sc` (sales channel) / region a VTEX: los precios de arriba son los
  del canal por defecto, que puede no ser el de La Plata.
- Falta la canasta real de Matias para pasar de 8.796 EAN comparables a los ~20
  que importan.
