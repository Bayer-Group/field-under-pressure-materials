// Step 3: render video.html frame by frame into an MP4 (1920x1080, 30 fps), with the soundtrack from music.mjs.
//   node showcase/render.mjs                    -> showcase/terranos-showcase.mp4
//   node showcase/render.mjs --stills 1,5.5,9   -> PNG stills in showcase/stills/ (quick checks)
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { launch } from './cdp.mjs'
import { writeSoundtrack } from './music.mjs'
import { STAMP, sourcesHash } from './video-sources.mjs'

const DIR = new URL('.', import.meta.url).pathname
const args = process.argv.slice(2)
const stills = args.includes('--stills') ? args[args.indexOf('--stills') + 1].split(',').map(Number) : null

const page = await launch({ width: 1920, height: 1080, scale: 1 })
try {
  await page.goto(`file://${DIR}video.html?render`, 500)
  await page.eval('window.ready')
  const { DURATION, FPS } = await page.eval('({ DURATION: window.DURATION, FPS: window.FPS })')

  if (stills) {
    mkdirSync(DIR + 'stills', { recursive: true })
    for (const t of stills) {
      await page.eval(`seek(${t})`)
      writeFileSync(`${DIR}stills/t${t.toFixed(2)}.png`, await page.screenshot())
      console.log('still', t)
    }
  } else {
    const hash = sourcesHash() // taken before rendering, so edits made mid-render count as changes
    const wav = DIR + 'soundtrack.wav'
    writeSoundtrack(wav, DURATION)
    const out = DIR + 'terranos-showcase.mp4'
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error',
      '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-', '-i', wav,
      '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
      '-c:a', 'aac', '-b:a', '192k', '-shortest', out], { stdio: ['pipe', 'inherit', 'inherit'] })
    const done = new Promise((res, rej) => ff.on('exit', (c) => (c ? rej(new Error('ffmpeg exit ' + c)) : res())))
    const n = Math.round(DURATION * FPS)
    for (let f = 0; f < n; f++) {
      await page.eval(`seek(${f / FPS})`)
      const jpg = await page.screenshot('jpeg', 95)
      if (!ff.stdin.write(jpg)) await new Promise((r) => ff.stdin.once('drain', r))
      if (f % 60 === 0) process.stdout.write(`frame ${f}/${n}\n`)
    }
    ff.stdin.end()
    await done
    writeFileSync(STAMP, hash + '\n')
    console.log('wrote', out)
  }
} finally {
  await page.close()
}
