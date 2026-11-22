// Fingerprint of everything the rendered video is made from, so export.mjs can tell whether
// terranos-showcase.mp4 still matches its sources. File mtimes can't: a git pull rewrites them.
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const DIR = new URL('.', import.meta.url).pathname
export const STAMP = join(DIR, 'terranos-showcase.mp4.sources')
const SOURCES = ['video.html', 'music.mjs', 'shots', 'brand']

const files = (p) => statSync(p).isDirectory()
  ? readdirSync(p).sort().flatMap((f) => files(join(p, f)))
  : [p]

export function sourcesHash() {
  const h = createHash('sha256')
  for (const f of SOURCES.map((s) => join(DIR, s)).filter(existsSync).flatMap(files)) {
    h.update(relative(DIR, f)).update('\0').update(readFileSync(f)).update('\0')
  }
  return h.digest('hex')
}
