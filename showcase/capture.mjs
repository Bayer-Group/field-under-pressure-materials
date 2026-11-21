// Step 1: capture real screens of the running GUI into showcase/shots/.
//   node showcase/capture.mjs [baseUrl]        (default http://127.0.0.1:8000; start it with scripts/12_gui.py)
import { writeFileSync, mkdirSync } from 'node:fs'
import { launch, sleep } from './cdp.mjs'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8000'
const OUT = new URL('./shots/', import.meta.url).pathname
const PLOT = 'KONA_001'        // rich aerial + greenness history
const FN_PLOT = 'STER_010'     // a deeply sequenced metagenome, so soil functions are ranked
mkdirSync(OUT, { recursive: true })

const page = await launch({ width: 1600, height: 900, scale: 1.5 })
// Each shot also records where its key elements sit (in screenshot pixels), so the video can zoom onto them.
const RECTS = {}
const MEASURE = {
  panel: '.panel', map: '.map-area', layer: '.layer-card', legend: '.ndvi-legend', tabs: '.tabs', head: '.plot-head',
  site: '.site-card', plotBtn: '.plot-grid a', marker: '.map path.leaflet-interactive, .map .leaflet-marker-icon',
  siteLabel: '.map .leaflet-tooltip', chart: '.panel svg', controls: '.controls', segBar: '.seg-bar', compTable: '.comp-table',
  search: '.taxon-search', card: '.dc-card', cards: '.dc-grid', ncycle: '.ncycle', page: '.page', evCard: '.page .card', pageHead: '.page-head',
  row: '.comp-table tr', ncBox: '.ncycle rect', statusBadge: '.dc-status',
}
const measure = () => page.eval(`(() => { const out = {}, k = 1.5
  for (const [name, sel] of Object.entries(${JSON.stringify(MEASURE)})) {
    const r = [...document.querySelectorAll(sel)].map(e => e.getBoundingClientRect())
      .filter(b => b.width > 0 && b.height > 0 && b.bottom > 0 && b.top < innerHeight)
      .map(b => [b.left * k, b.top * k, b.width * k, b.height * k].map(Math.round))
    if (r.length) out[name] = r }
  return out })()`)
const shot = async (name) => {
  writeFileSync(OUT + name + '.png', await page.screenshot())
  RECTS[name] = await measure()
  console.log('shot', name)
}
const js = (s) => JSON.stringify(s)
const scrollPanel = (y) => page.eval(`document.querySelector('.panel').scrollTo(0, ${y})`)
const scrollTo = (sel, pad = 90) => page.eval(`(() => { const p = document.querySelector('.panel'), n = document.querySelector(${js(sel)});
  if (n) p.scrollTo(0, n.getBoundingClientRect().top - p.getBoundingClientRect().top + p.scrollTop - ${pad}); return !!n })()`)
const click = (sel, text) => page.eval(`(() => {
  const el = [...document.querySelectorAll(${js(sel)})].find(e => e.textContent.trim().startsWith(${js(text)}))
  if (el) el.click(); return !!el })()`)
// Set a React-controlled <select> to the first option whose label matches.
const pick = (sel, re) => page.eval(`(() => {
  const s = document.querySelector(${js(sel)}); if (!s) return false
  const o = [...s.options].find(o => new RegExp(${js(re)}).test(o.textContent)); if (!o) return false
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value)
  s.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)

try {
  await page.goto(`${BASE}/#/`, 4000)
  await shot('overview')

  await page.goto(`${BASE}/#/plot/${PLOT}`, 5000)
  await shot('greenness')
  await click('.layer-card button', 'Greenness'); await sleep(1500)
  // A midsummer map is greener than the latest (November) one.
  await pick('.date-pick select:first-child', '^2025$'); await sleep(500)
  await pick('.date-pick select:last-child', 'Jul|Aug|Jun'); await sleep(3500)
  await shot('greenness-map')

  await page.goto(`${BASE}/#/plot/${PLOT}/microbes`, 4000)
  await click('.layer-card button', 'Aerial'); await sleep(2500)
  await shot('microbes')
  await click('.microbiome button, button', 'Fungi'); await sleep(2000)
  await click('.microbiome button, button', 'Genus'); await sleep(2000)
  await shot('microbes-fungi')

  await page.goto(`${BASE}/#/plot/${FN_PLOT}/functions`, 6000)
  await shot('functions')
  await scrollTo('.ncycle'); await sleep(800); await shot('functions-ncycle')

  const ev = await page.eval(`fetch('/api/plots/${PLOT}/events').then(r => r.json()).then(a => a.find(e => e.date.startsWith('2019-06'))?.event_id ?? a.at(-1).event_id)`)
  await page.goto(`${BASE}/#/event/${ev}`, 5000)
  await shot('event')
  writeFileSync(OUT + 'rects.json', JSON.stringify(RECTS, null, 1))
  writeFileSync(OUT + 'rects.js', `window.RECTS = ${JSON.stringify(RECTS)}\n`)  // loadable from file:// by video.html
} finally {
  await page.close()
}
