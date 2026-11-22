// Export the slide deck as a self-contained folder you can send to someone (opens from disk, no server).
//   node showcase/export.mjs          -> showcase/export/terranos-deck/
//   node showcase/export.mjs --zip    -> also showcase/export/terranos-deck.zip
import { spawnSync } from 'node:child_process'
import { cpSync, existsSync, readFileSync, readdirSync, rmSync, writeFileSync, mkdirSync } from 'node:fs'
import { basename, dirname, join, relative, resolve } from 'node:path'
import { STAMP, sourcesHash } from './video-sources.mjs'

const DIR = new URL('.', import.meta.url).pathname
const NAME = 'terranos-deck'
const OUT_ROOT = join(DIR, 'export')
const OUT = join(OUT_ROOT, NAME)
const VIDEO = join(DIR, 'terranos-showcase.mp4')
const zip = process.argv.includes('--zip')

const warnings = []
const warn = (msg) => { warnings.push(msg); console.warn('warning:', msg) }

// The demo break plays the rendered video; it's generated, so it may be missing or older than its sources.
if (!existsSync(VIDEO)) {
  console.error('error: showcase/terranos-showcase.mp4 is missing. Render it first (see showcase/README.md).')
  process.exit(1)
}
if (!existsSync(STAMP)) warn("can't tell whether terranos-showcase.mp4 is current (no render stamp); re-run render.mjs to be sure.")
else if (readFileSync(STAMP, 'utf8').trim() !== sourcesHash()) {
  warn('video.html, music.mjs, shots/ or brand/ changed since terranos-showcase.mp4 was rendered; re-run render.mjs.')
}

// Copy only what the deck loads: deck/ (minus its dev README), brand/, and the video, keeping their relative layout.
rmSync(OUT, { recursive: true, force: true })
mkdirSync(OUT, { recursive: true })
cpSync(join(DIR, 'deck'), join(OUT, 'deck'), {
  recursive: true,
  filter: (src) => relative(join(DIR, 'deck'), src) !== 'README.md',
})
cpSync(join(DIR, 'brand'), join(OUT, 'brand'), { recursive: true })
cpSync(VIDEO, join(OUT, basename(VIDEO)))

writeFileSync(join(OUT, 'Open presentation.html'), `<!doctype html>
<meta charset="utf-8">
<title>Terranos</title>
<meta http-equiv="refresh" content="0; url=deck/index.html">
<p>Opening the presentation… If nothing happens, open <a href="deck/index.html">deck/index.html</a>.</p>
`)

writeFileSync(join(OUT, 'README.txt'), `Terranos presentation

Open "Open presentation.html" (or deck/index.html) in Chrome, Edge, Firefox or Safari.
No internet or installation needed. Keep the folder together: the slides load the
images in brand/ and the video terranos-showcase.mp4 from next to them.

Keys
  Right arrow / Space   next step or slide
  Left arrow            back
  F                     fullscreen
  O / Esc               overview of all slides
  R                     replay the current slide's animation

The demo slide plays a one-minute video with sound. If the browser starts it muted,
click the video or press R.
`)

// Check every relative path the page and its stylesheets reference resolves inside the export,
// so an asset added later from outside deck/ or brand/ doesn't silently go missing.
const refs = (file, re) => [...readFileSync(file, 'utf8').matchAll(re)].map((m) => [file, m[1]])
const isLocal = (p) => p && !/^(https?:|data:|#|mailto:|\/\/)/.test(p)
const cssDir = join(OUT, 'deck', 'css')
const checks = [
  ...refs(join(OUT, 'deck', 'index.html'), /\b(?:src|href)="([^"]+)"/g),
  ...readdirSync(cssDir).filter((f) => f.endsWith('.css')).flatMap((f) => refs(join(cssDir, f), /url\(\s*['"]?([^'")]+)['"]?\s*\)/g)),
]
for (const [file, ref] of checks) {
  if (!isLocal(ref)) continue
  const target = resolve(dirname(file), decodeURI(ref.split(/[?#]/)[0]))
  if (!target.startsWith(OUT + '/')) warn(`${relative(OUT, file)} references ${ref}, which is outside the export.`)
  else if (!existsSync(target)) warn(`${relative(OUT, file)} references ${ref}, which isn't in the export.`)
}

const todos = (readFileSync(join(OUT, 'deck', 'index.html'), 'utf8').match(/todo/gi) || []).length
if (todos) warn(`deck/index.html still has ${todos} "todo" marker(s); they show as orange badges on screen.`)

const du = spawnSync('du', ['-sh', OUT], { encoding: 'utf8' }).stdout?.split('\t')[0]
console.log(`exported ${relative(process.cwd(), OUT) || OUT}${du ? ` (${du})` : ''}`)

if (zip) {
  const zipPath = join(OUT_ROOT, `${NAME}.zip`)
  rmSync(zipPath, { force: true })
  const r = spawnSync('zip', ['-r', '-q', '-X', zipPath, NAME], { cwd: OUT_ROOT, stdio: 'inherit' })
  if (r.error || r.status) {
    console.error('error: zip failed' + (r.error ? ` (${r.error.message}); is the zip command installed?` : ''))
    process.exit(1)
  }
  console.log(`zipped ${relative(process.cwd(), zipPath)}`)
}

if (warnings.length) console.warn(`${warnings.length} warning(s), see above.`)
