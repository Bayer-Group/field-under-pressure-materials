// Step 1: capture real screens of the running GUI into showcase/shots/.
//   node showcase/capture.mjs [baseUrl]        (default http://127.0.0.1:8000; start it with scripts/12_gui.py)
// The server must be current: the Roles view and the treatment plan need their API routes.
import { writeFileSync, mkdirSync } from 'node:fs'
import { launch, sleep } from './cdp.mjs'

const BASE = process.argv[2] ?? 'http://127.0.0.1:8000'
const OUT = new URL('./shots/', import.meta.url).pathname
// One plot carries the whole story: deep bacterial sequencing (taxonomy, roles, soil characteristics),
// a high corn risk on the crop disease heatmap and a corn treatment plan with "Buy now".
const PLOT = 'STER_010'
const K = 1.5 // device scale: shots are 2400 x 1350
mkdirSync(OUT, { recursive: true })

const page = await launch({ width: 1600, height: 900, scale: K })
// Each shot also records where its key elements sit (in screenshot pixels), so the video can zoom onto them.
const RECTS = {}
const MEASURE = {
  panel: '.panel', map: '.map-area', tabs: '.tabs', head: '.plot-head', overviewHead: '.overview > h1, .overview > .lead',
  site: '.site-card', plotBtn: '.plot-grid a', zoomSite: '.zoom-site', marker: '.map path.leaflet-interactive',
  controls: '.controls', segBar: '.seg-bar', legend: '.comp-legend', search: '.taxon-search', row: '.comp-table tbody tr',
  roleRow: '.role-row', roleTree: '.role-tree', chartHead: '.chart-head', viewToggle: '.segmented',
  scCard: '.sc-card', scSection: '.sc-section', tagOk: '.sc-tag.ok', tagLook: '.sc-tag.look',
  heat: '.heat', heatCell: '.heat-cell', heatOn: '.heat-cell.on', heatCol: '.heat-col',
  planCol: '.plan-col', planItem: '.plan-item', buyNow: '.buy-now', cropPick: '.choice',
  layerCard: '.layer-card', ndviLegend: '.ndvi-legend',
}
const measure = () => page.eval(`(() => { const out = {}, k = ${K}
  for (const [name, sel] of Object.entries(${JSON.stringify(MEASURE)})) {
    const r = [...document.querySelectorAll(sel)].map(e => e.getBoundingClientRect())
      .filter(b => b.width > 0 && b.height > 0 && b.bottom > 0 && b.top < innerHeight)
      .map(b => [b.left * k, b.top * k, b.width * k, b.height * k].map(Math.round))
    if (r.length) out[name] = r }
  return out })()`)
const shot = async (name, extra = {}) => {
  writeFileSync(OUT + name + '.png', await page.screenshot())
  RECTS[name] = { ...(await measure()), ...extra }
  console.log('shot', name)
}
const js = (s) => JSON.stringify(s)
/** Rect of one element in screenshot pixels. */
const rectOf = (sel) => page.eval(`(() => { const b = document.querySelector(${js(sel)})?.getBoundingClientRect()
  return b ? [b.left * ${K}, b.top * ${K}, b.width * ${K}, b.height * ${K}].map(Math.round) : null })()`)
const click = (sel, text) => page.eval(`(() => {
  const el = [...document.querySelectorAll(${js(sel)})].find(e => e.textContent.trim().startsWith(${js(text)}))
  if (el) el.click(); return !!el })()`)
const hover = async (sel) => {
  const r = await rectOf(sel)
  if (!r) return false
  const [x, y] = [(r[0] + r[2] / 2) / K, (r[1] + r[3] / 2) / K]
  await page.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y })
  return true
}
const scrollTo = (sel, pad = 90) => page.eval(`(() => { const p = document.querySelector('.panel'), n = document.querySelector(${js(sel)});
  if (n) p.scrollTo(0, n.getBoundingClientRect().top - p.getBoundingClientRect().top + p.scrollTop - ${pad}); return !!n })()`)
// Set a React-controlled <select> to the first option whose label matches.
const pick = (sel, re) => page.eval(`(() => {
  const s = document.querySelector(${js(sel)}); if (!s) return false
  const o = [...s.options].find(o => new RegExp(${js(re)}).test(o.textContent)); if (!o) return false
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value)
  s.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)

try {
  // A deep link skips the landing screen; the hash change back to the overview keeps it skipped.
  await page.goto(`${BASE}/#/plot/${PLOT}`, 2500)
  await page.goto(`${BASE}/#/`, 3500)
  await shot('overview')
  await page.eval(`[...document.querySelectorAll('.site-card')].find(s => s.textContent.includes('Sterling'))?.querySelector('.zoom-site')?.click()`)
  await sleep(3500)
  await shot('overview-site')
  const btn = `.plot-grid a[href="#/plot/${PLOT}"]`
  await hover(btn); await sleep(900)
  await shot('overview-hot', { hotBtn: [await rectOf(btn)] })

  await page.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 5, y: 5 })
  await page.goto(`${BASE}/#/plot/${PLOT}/microbes?view=taxonomy`, 5000)
  await shot('microbes')

  await page.goto(`${BASE}/#/plot/${PLOT}/microbes?view=roles`, 4500)
  await shot('roles')
  await scrollTo('.roles-h', 30); await sleep(800)
  await shot('roles-tree')

  await page.goto(`${BASE}/#/plot/${PLOT}/functions`, 5000)
  await shot('functions')

  await page.goto(`${BASE}/#/plot/${PLOT}/risk`, 5000)
  await shot('risk')

  await page.goto(`${BASE}/#/plot/${PLOT}/plan`, 5000)
  await shot('plan')

  await page.goto(`${BASE}/#/plot/${PLOT}/greenness`, 5000)
  await shot('greenness')
  await click('.layer-card button', 'Greenness'); await sleep(1500)
  await pick('.date-pick select:first-child', '^2023$'); await sleep(500)
  await pick('.date-pick select:last-child', 'Jul|Aug|Jun'); await sleep(3500)
  await shot('greenness-map')

  writeFileSync(OUT + 'rects.json', JSON.stringify(RECTS, null, 1))
  writeFileSync(OUT + 'rects.js', `window.RECTS = ${JSON.stringify(RECTS)}\n`)  // loadable from file:// by video.html
} finally {
  await page.close()
}
