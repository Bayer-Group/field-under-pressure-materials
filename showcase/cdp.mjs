// Minimal Chrome DevTools Protocol client: launches headless Chromium and drives one page.
// No dependencies (Node >= 22 has a global WebSocket).
import { spawn } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export async function launch({ width = 1920, height = 1080, scale = 1 } = {}) {
  const profile = mkdtempSync(join(tmpdir(), 'cdp-'))
  const proc = spawn('chromium', [
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--mute-audio', '--no-first-run',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, `--window-size=${width},${height}`, 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'] })
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = ''
    proc.stderr.on('data', (d) => {
      buf += d
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/)
      if (m) resolve(m[1])
    })
    proc.on('exit', () => reject(new Error('chromium exited:\n' + buf)))
  })
  const port = new URL(wsUrl).port
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json()
  const pageTarget = targets.find((t) => t.type === 'page')
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl)
  await new Promise((r) => ws.addEventListener('open', r, { once: true }))
  let id = 0
  const pending = new Map()
  const listeners = []
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
    } else if (msg.method) listeners.forEach((l) => l(msg))
  })
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const i = ++id
    pending.set(i, { resolve, reject })
    ws.send(JSON.stringify({ id: i, method, params }))
  })
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile: false })

  const page = {
    send,
    async goto(url, settleMs = 1500) {
      const loaded = new Promise((r) => {
        const l = (m) => { if (m.method === 'Page.loadEventFired') { listeners.splice(listeners.indexOf(l), 1); r() } }
        listeners.push(l)
      })
      await send('Page.navigate', { url })
      // A hash-only change does not fire a load event: give up waiting after a few seconds.
      await Promise.race([loaded, sleep(4000)])
      await sleep(settleMs)
    },
    async eval(expr) {
      const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text)
      return r.result.value
    },
    async screenshot(format = 'png', quality) {
      const r = await send('Page.captureScreenshot', { format, ...(quality ? { quality } : {}), captureBeyondViewport: false })
      return Buffer.from(r.data, 'base64')
    },
    async close() { try { await send('Browser.close') } catch { /* closing */ } proc.kill() },
  }
  return page
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
