/* Captura de precios de PedidosYa desde tu propia sesion del navegador.
 *
 * Por que asi y no con un scraper: PedidosYa esta detras de PerimeterX, que
 * devuelve 403 a cualquier request que no venga de un navegador real, y su
 * robots.txt prohibe /mobile/v3* (que es justamente la API del catalogo).
 * Este snippet no scrapea nada: se cuelga de fetch/XHR y guarda las respuestas
 * que la propia pagina ya pidio mientras vos navegas. Tu sesion, tu trafico.
 *
 * USO
 *   1. Abri PedidosYa en Chrome, con la direccion de La Plata ya elegida.
 *   2. F12 -> Console -> pega todo este archivo -> Enter.
 *   3. Entra a PeYa Market y a Carrefour, y navega las categorias que te
 *      importan (o busca cada producto). Cada respuesta queda registrada.
 *   4. Volve a la consola y corre:  __py.save()
 *      Baja un archivo py-YYYY-MM-DD.json a tu carpeta de descargas.
 *   5. Move ese archivo a  data/py/  del proyecto.
 *
 * Comandos disponibles: __py.stats()  __py.save()  __py.reset()  __py.off()
 */

(() => {
  if (window.__py) {
    console.warn('[py] ya estaba activo. __py.stats() para ver que hay.');
    return;
  }

  const captures = [];
  const MAX_BYTES = 40 * 1024 * 1024; // corta antes de reventar la memoria del tab
  let bytes = 0;
  let stopped = false;

  // Solo interesa el trafico de catalogo. Todo lo demas (analytics, mapas,
  // imagenes, tracking) es ruido y engorda el archivo sin aportar precios.
  const INTERESTING = /(product|catalog|search|menu|item|categor|shop|store|vendor|grocer|listing|price)/i;
  const IGNORE = /(analytics|segment|datadog|sentry|newrelic|hotjar|braze|amplitude|googletag|doubleclick|facebook|clarity|\.(png|jpe?g|webp|svg|gif|css|woff2?|ico)(\?|$))/i;

  const wanted = (url) => !IGNORE.test(url) && INTERESTING.test(url);

  function record(url, method, status, body) {
    if (stopped || !body || bytes >= MAX_BYTES) return;
    let parsed;
    try {
      parsed = JSON.parse(body);
    } catch {
      return; // no es JSON: no sirve
    }
    bytes += body.length;
    captures.push({
      url,
      method,
      status,
      // ts lo pone el navegador; el pipeline usa la fecha del nombre del archivo
      ts: new Date().toISOString(),
      body: parsed,
    });
    if (bytes >= MAX_BYTES) {
      console.warn('[py] limite de 40 MB alcanzado, dejo de registrar. Corre __py.save().');
    }
  }

  // --- fetch ---------------------------------------------------------------
  const realFetch = window.fetch;
  window.fetch = async function (...args) {
    const response = await realFetch.apply(this, args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : args[0]?.url ?? '';
      if (wanted(url)) {
        const method = args[1]?.method || (typeof args[0] === 'object' ? args[0]?.method : 'GET') || 'GET';
        // clone() para no consumir el body que la pagina todavia va a leer
        response.clone().text().then((t) => record(url, method, response.status, t)).catch(() => {});
      }
    } catch {
      /* nunca romper la pagina por la captura */
    }
    return response;
  };

  // --- XMLHttpRequest ------------------------------------------------------
  const realOpen = XMLHttpRequest.prototype.open;
  const realSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__pyUrl = url;
    this.__pyMethod = method;
    return realOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener('load', () => {
      try {
        if (wanted(this.__pyUrl || '')) {
          record(this.__pyUrl, this.__pyMethod, this.status, this.responseText);
        }
      } catch {
        /* idem */
      }
    });
    return realSend.apply(this, args);
  };

  // --- estado inicial de la pagina ----------------------------------------
  // Muchas pantallas de PeYa vienen server-side rendered: el primer lote de
  // productos ya esta en el HTML y nunca pasa por fetch. Sin esto, la primera
  // pantalla de cada categoria se pierde.
  function grabInitialState() {
    for (const id of ['__NEXT_DATA__', '__APOLLO_STATE__', '__INITIAL_STATE__']) {
      const el = document.getElementById(id);
      if (el?.textContent) {
        record(`initial://${id}${location.pathname}`, 'INIT', 200, el.textContent);
      }
    }
    for (const key of ['__APOLLO_STATE__', '__INITIAL_STATE__', '__PRELOADED_STATE__']) {
      if (window[key]) {
        try {
          record(`initial://window.${key}${location.pathname}`, 'INIT', 200, JSON.stringify(window[key]));
        } catch {
          /* estados con ciclos: se ignoran */
        }
      }
    }
  }
  grabInitialState();
  // Al cambiar de categoria la SPA reescribe el estado sin recargar.
  const origPush = history.pushState;
  history.pushState = function (...a) {
    const r = origPush.apply(this, a);
    setTimeout(grabInitialState, 1200);
    return r;
  };

  window.__py = {
    stats() {
      const byHost = {};
      for (const c of captures) {
        let h = 'initial';
        try { h = new URL(c.url, location.origin).pathname.split('/').slice(0, 4).join('/'); } catch {}
        byHost[h] = (byHost[h] || 0) + 1;
      }
      console.table(byHost);
      console.log(`[py] ${captures.length} respuestas, ${(bytes / 1e6).toFixed(1)} MB`);
      return captures.length;
    },
    save(name) {
      const d = new Date();
      const stamp = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const payload = {
        schema: 'py-capture/1',
        captured_at: d.toISOString(),
        page_url: location.href,
        count: captures.length,
        captures,
      };
      const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name || `py-${stamp}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      console.log(`[py] guardado ${a.download} (${captures.length} respuestas)`);
    },
    reset() {
      captures.length = 0;
      bytes = 0;
      console.log('[py] limpio');
    },
    off() {
      stopped = true;
      window.fetch = realFetch;
      XMLHttpRequest.prototype.open = realOpen;
      XMLHttpRequest.prototype.send = realSend;
      history.pushState = origPush;
      console.log('[py] desenganchado');
    },
  };

  console.log('%c[py] capturando. Navega PeYa Market y Carrefour, despues corre __py.save()', 'color:#0a0');
})();
