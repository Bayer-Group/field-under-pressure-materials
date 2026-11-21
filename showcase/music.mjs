// The soundtrack, synthesized in code: 120 bpm, A minor (Am - F - C - G), cut points on the bar lines of the video.
// writeSoundtrack(path, seconds) writes a 16-bit stereo WAV. Run directly to write showcase/soundtrack.wav.
import { writeFileSync } from 'node:fs'

const SR = 44100, BPM = 120, BEAT = 60 / BPM, BAR = 4 * BEAT
// Scene cuts in the video (seconds): each gets a whoosh into it.
const CUTS = [4, 8, 12, 14, 18, 21, 24, 26]
const CHORDS = [ // [bass Hz, chord tones Hz]
  [110.0, [220.0, 261.63, 329.63]],   // Am
  [87.31, [174.61, 220.0, 261.63]],   // F
  [130.81, [261.63, 329.63, 392.0]],  // C
  [98.0, [196.0, 246.94, 293.66]],    // G
]

export function writeSoundtrack(path, seconds = 30) {
  const n = Math.round(seconds * SR)
  const L = new Float32Array(n), R = new Float32Array(n)
  let seed = 12345
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296) * 2 - 1

  const add = (i, v, pan = 0) => { if (i >= 0 && i < n) { L[i] += v * (1 - Math.max(0, pan)); R[i] += v * (1 + Math.min(0, pan)) } }
  const osc = (type, ph) => {
    const x = ph % 1
    return type === 'sine' ? Math.sin(2 * Math.PI * x) : type === 'saw' ? 2 * x - 1 : type === 'square' ? (x < 0.5 ? 1 : -1) : 1 - 4 * Math.abs(x - 0.5)
  }

  /** Oscillator voice with ADSR-ish envelope and a one-pole lowpass. */
  function voice(t0, dur, freq, { type = 'saw', gain = 0.1, a = 0.01, r = 0.2, cutoff = 4000, pan = 0, detune = 0 } = {}) {
    const s0 = Math.round(t0 * SR), len = Math.round((dur + r) * SR)
    let lp = 0, ph1 = 0, ph2 = 0
    const k = 1 - Math.exp((-2 * Math.PI * cutoff) / SR)
    for (let j = 0; j < len; j++) {
      const t = j / SR
      const env = Math.min(1, t / a) * (t < dur ? 1 : Math.max(0, 1 - (t - dur) / r))
      ph1 += freq / SR; ph2 += (freq * (1 + detune)) / SR
      const v = detune ? (osc(type, ph1) + osc(type, ph2)) / 2 : osc(type, ph1)
      lp += k * (v - lp)
      add(s0 + j, lp * env * gain, pan)
    }
  }
  function kick(t0, gain = 0.9) {
    const s0 = Math.round(t0 * SR); let ph = 0
    for (let j = 0; j < 0.42 * SR; j++) {
      const t = j / SR, f = 45 + 110 * Math.exp(-t * 28)
      ph += f / SR
      add(s0 + j, Math.sin(2 * Math.PI * ph) * Math.exp(-t * 7) * gain + (j < 60 ? rnd() * 0.15 * (1 - j / 60) : 0))
    }
  }
  function noiseHit(t0, dur, { gain = 0.2, hp = 0, lp = 9000, decay = 30, pan = 0 } = {}) {
    const s0 = Math.round(t0 * SR); let a = 0, b = 0
    const ka = 1 - Math.exp((-2 * Math.PI * lp) / SR), kb = 1 - Math.exp((-2 * Math.PI * Math.max(hp, 1)) / SR)
    for (let j = 0; j < dur * SR; j++) {
      const t = j / SR
      a += ka * (rnd() - a); b += kb * (a - b)
      add(s0 + j, (hp ? a - b : a) * Math.exp(-t * decay) * gain, pan)
    }
  }
  /** Filtered noise swelling up to time `at`, then a short tail. */
  function whoosh(at, len = 0.55, gain = 0.28) {
    const t0 = at - len, s0 = Math.round(t0 * SR); let a = 0
    for (let j = 0; j < (len + 0.25) * SR; j++) {
      const t = j / SR, p = Math.min(1, t / len)
      const cut = 300 + 7000 * p * p
      const k = 1 - Math.exp((-2 * Math.PI * cut) / SR)
      a += k * (rnd() - a)
      const env = t < len ? p ** 2 : Math.exp(-(t - len) * 14)
      add(s0 + j, a * env * gain, Math.sin(t * 9) * 0.6)
    }
  }

  const DRUMS_FROM = 2, DRUMS_TO = 28
  const bars = Math.ceil(seconds / BAR)
  for (let b = 0; b < bars; b++) {
    const t0 = b * BAR, [bass, chord] = CHORDS[b % 4]
    const intro = t0 < DRUMS_FROM, outro = t0 >= DRUMS_TO
    // pad: always, softer in the busy middle
    for (const [i, f] of chord.entries()) voice(t0, BAR, f, { type: 'saw', gain: intro || outro ? 0.05 : 0.032, a: 0.3, r: 0.6, cutoff: intro ? 900 + 600 * (t0 / 2) : 1400, detune: 0.006, pan: (i - 1) * 0.5 })
    if (intro || outro) continue
    for (let q = 0; q < 8; q++) {
      const t = t0 + q * BEAT / 2
      // bass on eighths, octave jump on the offbeat
      voice(t, BEAT / 2 * 0.8, q % 2 ? bass * 2 : bass, { type: 'square', gain: 0.11, a: 0.004, r: 0.05, cutoff: 600 })
      // pluck arpeggio
      const note = chord[[0, 1, 2, 1, 2, 0, 1, 2][q]] * 2
      voice(t, 0.09, note, { type: 'triangle', gain: 0.075, a: 0.002, r: 0.25, cutoff: 5000, pan: q % 2 ? 0.35 : -0.35 })
      // drums
      if (q % 2 === 0) kick(t)
      if (q % 2 === 1) noiseHit(t, 0.06, { gain: 0.12, hp: 7000, decay: 60, pan: 0.2 })
      if (q === 2 || q === 6) noiseHit(t, 0.22, { gain: 0.32, hp: 900, lp: 6000, decay: 18 })
    }
    // 16th hats on the second half of each bar for drive
    for (let s = 8; s < 16; s++) noiseHit(t0 + s * BEAT / 4, 0.03, { gain: 0.05, hp: 9000, decay: 90, pan: -0.25 })
  }
  // intro riser into the drop at 2 s, plus shimmer on the logo
  whoosh(2, 1.6, 0.25)
  for (let i = 0; i < 6; i++) voice(0.2 + i * 0.12, 0.25, [659.25, 783.99, 880, 987.77, 1174.66, 1318.51][i], { type: 'sine', gain: 0.05, a: 0.005, r: 0.6, pan: (i % 2 ? 0.5 : -0.5) })
  for (const c of CUTS) whoosh(c)
  // impact into the outro and a closing chord
  kick(26, 1.1); noiseHit(26, 1.6, { gain: 0.22, hp: 3000, decay: 2.5 })
  for (const f of [110, 220, 261.63, 329.63, 440]) voice(28, 1.6, f, { type: 'saw', gain: 0.04, a: 0.02, r: 0.4, cutoff: 1800, detune: 0.005 })

  // master: soft clip, normalise to -1 dBFS, fade the last 0.6 s
  let peak = 0
  for (let i = 0; i < n; i++) { L[i] = Math.tanh(L[i] * 1.2); R[i] = Math.tanh(R[i] * 1.2); peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i])) }
  const g = 0.89 / peak, fadeFrom = n - 0.6 * SR
  const buf = Buffer.alloc(44 + n * 4)
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 4, 4); buf.write('WAVEfmt ', 8)
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(2, 22); buf.writeUInt32LE(SR, 24)
  buf.writeUInt32LE(SR * 4, 28); buf.writeUInt16LE(4, 32); buf.writeUInt16LE(16, 34); buf.write('data', 36); buf.writeUInt32LE(n * 4, 40)
  for (let i = 0; i < n; i++) {
    const f = i > fadeFrom ? 1 - (i - fadeFrom) / (n - fadeFrom) : 1
    buf.writeInt16LE(Math.round(L[i] * g * f * 32767), 44 + i * 4)
    buf.writeInt16LE(Math.round(R[i] * g * f * 32767), 46 + i * 4)
  }
  writeFileSync(path, buf)
}

if (import.meta.url === `file://${process.argv[1]}`) writeSoundtrack(new URL('./soundtrack.wav', import.meta.url).pathname)
