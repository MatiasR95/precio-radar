# precio-radar — handoff

Read this first in a new session, then `NOTES-fase1.md` for the deep detail on
PedidosYa's API and every trap already hit. `NOTES-fase0.md` covers the SEPA feed.

Inline code comments and the NOTES files are in Spanish (Matías is in La Plata,
Argentina). This file is in English because it's operational.

---

## What this is

A daily price radar for Matías's grocery basket. It answers two separate
questions, and keeping them separate is the whole design:

- **DÓNDE** — for each basket line, is it cheaper today at *PedidosYa Market* or
  at *Carrefour*, both **inside PedidosYa**. Answered from today's run alone.
- **CUÁNDO** — is today's price actually low for that product, measured against
  its own history. This is what separates a real promo from the usual price with
  a badge stuck on it. Needs accumulated days; below the threshold it says how
  many are missing instead of inventing a trend.

Published daily to **https://matiasr95.github.io/precio-radar/**
Repo: `github.com/MatiasR95/precio-radar` (public, no secrets).

## Status as of 2026-08-12

| | |
|---|---|
| Series | 7.758 rows — 7.473 SEPA, 285 PedidosYa — across 8 dates (08-05 → 08-12) |
| PedidosYa history | **1 day.** The "cuándo" verdict needs 7, so everything currently reads `faltan 7 días`. This is correct, not a bug. |
| EAN-confirmed rows | 14 of 285. The rest are provisional variants. |
| Scheduled task | `precio-radar`, Windows Task Scheduler, daily 12:30, `StartWhenAvailable` |
| First unattended run | 2026-08-13 12:30 — **had not happened yet when this was written** |

The single most useful thing early in a new session: check whether the daily runs
have actually been firing. If the page shows a yellow staleness banner, they
haven't, and `data/run-daily.log` says why.

## The daily loop

`run-daily.cmd` (invoked by Task Scheduler) runs:

```
py_fetch.py daily   →  data/py/py-YYYY-MM-DD.json
store.py py         →  appends into data/serie.csv
report.py           →  data/reporte.md + data/reporte.html + docs/index.html
git add/commit/push →  GitHub Pages
```

It **stops at the first failure and publishes nothing**. A half-empty day that
looks like prices moved is worse than yesterday's data staying up.

## Commands

```bash
python src/py_fetch.py login      # opens Edge; solve captcha, close window when done
python src/py_fetch.py discover   # records raw API responses (one-off, already done)
python src/py_fetch.py daily      # the unattended fetch
python src/store.py py            # ingest latest py-*.json
python src/store.py sepa [zip]    # ingest one SEPA day (downloads today's if no path)
python src/store.py seed          # all 7 weekday ZIPs = a week of history, ~2 GB
python src/report.py [fecha]      # rebuild the report; never touches the network
python src/test_seleccion.py      # test match rules offline against captured responses
```

PowerShell 5.1 has **no `&&`** — chain with `;`.

## Architecture

| File | Job |
|---|---|
| `src/py_fetch.py` | Talks to PedidosYa through a real Edge browser with a persistent profile. |
| `src/store.py` | `data/serie.csv`, long format, one row per (fecha, fuente, tienda, ean). Idempotent per (fecha, fuente). |
| `src/report.py` | All the calculation: comparison, per-unit normalisation, verdict. |
| `src/page.py` | Only the HTML/CSS. Design lives here, math lives in `report.py`. |
| `src/sepa.py` | Government SEPA feed reader (from fase 0). |
| `src/match.py` | Basket match rules, shared by the SEPA and PedidosYa paths. |
| `src/test_seleccion.py` | Replays `discovery-*.json` through the selection rules. **Use this to iterate on rules — it never hits the network.** |
| `basket.yaml` | The basket. Match rules, store IDs, accepted/rejected EANs. |

## Things that are true and cost real time to learn

**PedidosYa cannot be scraped with `requests`.** PerimeterX 403s everything that
isn't a real browser — including `sitemap.xml`, which they publish in their own
robots.txt. Hence Playwright + Edge + persistent profile (`data/browser-profile/`,
gitignored, holds the login and the `_px3` cookie — treat it as a credential).

**Playwright's `ctx.request` also gets 403.** It carries cookies but not the
headers PY's JS client adds. API calls must go through a same-origin `fetch`
inside the page (`page.evaluate`). This is what `api_get()` does.

**`gtin` is the EAN.** PY publishes GTIN-14 with leading zeros
(`08445291786721`); strip them and it joins to SEPA and to the VTEX stores
exactly. No fuzzy text matching anywhere in the join.

**Search and detail return different schemas** for the same product — snake_case
flat vs camelCase with a nested `pricing`. Search also has stale `stock` and no
`beforePrice`, so search finds the id and detail supplies the recorded price.

**Rate limit is real and easy to trip.** ~200 calls in a few minutes got the whole
session blocked down to the homepage; recovery needs `login` and a manual captcha.
The daily run is ~50 calls at 2 s spacing. **Never re-run `daily` repeatedly to
test something** — iterate with `report.py` and `test_seleccion.py`.

**SEPA's weekday ZIP is not today's data.** Downloaded on Wednesday 2026-08-12,
`sepa_miercoles.zip` contained the folder `2026-08-05/`. The date is read from
inside the ZIP and ingest refuses if it can't find one. The same mechanism is why
`seed` works: the 7 weekday ZIPs are 7 different dates.

**Never compare across sources.** A PedidosYa price against a SEPA shelf median
made 10 of 17 products announce "cheapest ever" on day one — PeYa Market simply
sits below those chains. Verdicts use PedidosYa history only; SEPA appears as a
separate góndola cycle signal compared against itself.

**Rank by price per unit, not package price.** Otherwise the smallest bottle wins
every time. Papel higiénico and rollo de cocina need the measurement parsed out of
the product *name* (`(30 m) 4 Unidades` → 120 m), because PY reports them as `un`.

### The pattern behind every bug so far

Every single one produced believable output and threw no error: wrong dates,
mixed sources, cheapest-package ranking, a 403 that looked like "no results",
a competing brand silently becoming the headline price. **When something here
looks right, check it against a case where you know the answer.** That is how all
of them were caught.

## Basket model

- `accepted_eans` — whitelist of known-good variants. These get the detail call
  (authoritative price + stock) and can appear on the front page.
- `rejected_eans` — blacklist. Never tracked.
- Anything else passing the match rules is a **provisional variant**: tracked,
  flagged `sin_confirmar`, listed under "Por confirmar" for Matías to rule on.
- `variantes: false` — the line is one product, not a family (only
  `leche-protein`). The front page uses accepted EANs only; alternatives are
  still recorded.
- `formato` — presentation filter. Distinguishes Starbucks Nespresso (10 caps /
  51-57 g) from Dolce Gusto (12 / ~120 g). Handles `content_quantity` arriving in
  either units or grams.

## Open work, roughly in priority order

1. **Confirm the daily runs are firing.** Nothing else matters if the series
   isn't growing. Check the page for a staleness banner.
2. **Prune provisional variants.** Matías rules on them; move the wrong ones to
   `rejected_eans`. Genuine taste calls left open: the *yogur* family spans
   Tregar/Dahi/Milkaut and *desodorante* spans Old Spice/Axe/Arm & Hammer.
3. **More animation on the page.** Matías explicitly wants "lots of animated
   stuff". There is currently exactly one animation (a 40 ms staggered card
   entrance). Note: `prefers-reduced-motion` at `src/page.py:118` is NOT a limit
   he set — it's the OS accessibility preference, and motion is already on by
   default. Keep that guard when adding more.
4. **Verify the 680 px two-column breakpoint** on a real wide screen. The
   preview pane maxed out at 360 px, so it was never seen.
5. **Investigate six items all showing exactly 86% on the góndola signal**
   (yerba, detergente, lavandina, rollo, café, desodorante). Could be a genuine
   promo week or an artifact of the 08-12 SEPA file being thinner (836 rows vs
   ~950). One more day of data settles it.
6. **SEPA is not in the daily chain.** `store.py sepa` works but downloads
   300 MB; deliberately kept out of the unattended task.
7. **Carrefour stock always reads 0** in PY responses, including products it
   clearly sells. Until seen non-zero once, use its price and ignore its stock.

## Matías's preferences

- **$0 / serverless-first.** GitHub Pages, GitHub Actions cron, no paid services.
  This project deviates on one point for a reason: the PedidosYa fetch needs a
  persistent logged-in browser, which an ephemeral runner can't provide, so it
  runs locally via Task Scheduler.
- **Wants motion.** See item 3.
- **Confirms products himself.** Don't auto-promote provisional variants into
  `accepted_eans` — surface them and let him decide. He added
  *Las Tres Niñas Vida Activa* that way.
- Before adding any `schedule:` GitHub Actions workflow, read
  `../github-actions-minutes-playbook.md`. The ceiling is ~1500 billable
  runs/month across the whole account.

## Do not

- Commit `data/browser-profile/` — it holds his PedidosYa session.
- Commit `data/py/discovery-*.json` — can contain his address and order history.
- Solve or bypass CAPTCHAs. When PerimeterX challenges, stop and ask him to run
  `login`. That handoff to a human is the design, not a workaround.
- Re-run `daily` several times in a row while debugging. See rate limit above.
