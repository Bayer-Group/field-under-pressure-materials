// The soundtrack, synthesized in code: 120 bpm (one bar = 2 s), sections following video.html's storyboard.
// writeSoundtrack(path, seconds) writes a 16-bit stereo WAV. Run directly to write showcase/soundtrack.wav.
//    0 –  4  intro: pad, logo shimmer, riser            24 – 32  data break: half-time, sparkling 16ths, riser
//    4 – 24  groove (Am F C G) under the app tour       32 – 38  groove again (crop disease risk)
//   38 – 48  two neighbours, playful (C G Am F, oom-pah)  48 – 52  sad (Am Dm), the corn falls ill
//   52 – 58  hopeful (F G): he listens, "ding" on the purchase   58 – 60  happy fanfare (C)
//   60 – 66  outro: impact and closing chord
import { writeFileSync } from 'node:fs'

const SR = 44100, BPM = 120, BEAT = 60 / BPM, BAR = 4 * BEAT
// Wipes between scenes (seconds): each gets a whoosh into it.
const CUTS = [4, 24, 32, 38, 60]
const N = { A2: 110, D3: 146.83, E3: 164.81, F2: 87.31, G2: 98, C3: 130.81, A3: 220, C4: 261.63, D4: 293.66, E4: 329.63, F3: 174.61, F4: 349.23, G3: 196, G4: 392, A4: 440, B3: 246.94, C5: 523.25, E5: 659.25, G5: 783.99 }
const CH = {
  Am: [N.A2, [N.A3, N.C4, N.E4]], F: [N.F2, [N.F3, N.A3, N.C4]], C: [N.C3, [N.C4, N.E4, N.G4]], G: [N.G2, [N.G3, N.B3, N.D4]],
  Dm: [73.42, [N.F3, N.A3, N.D4]],
}
/** Section and chord of each 2-second bar. */
function bar(b) {
  const t = b * BAR
  if (t < 4) return { sec: 'intro', ch: ['Am', 'F'][b % 2] }
  if (t < 24) return { sec: 'groove', ch: ['Am', 'F', 'C', 'G'][(b - 2) % 4] }
  if (t < 32) return { sec: 'data', ch: ['Am', 'F', 'C', 'G'][(b - 12) % 4] }
  if (t < 38) return { sec: 'groove', ch: ['Am', 'F', 'G'][(b - 16) % 3] }
  if (t < 48) return { sec: 'play', ch: ['C', 'G', 'Am', 'F'][(b - 19) % 4] }
  if (t < 52) return { sec: 'sad', ch: ['Am', 'Dm'][(b - 24) % 2] }
  if (t < 58) return { sec: 'hope', ch: ['F', 'G'][(b - 26) % 2] }
  if (t < 60) return { sec: 'happy', ch: 'C' }
  return { sec: 'outro', ch: ['Am', 'F', 'C'][(b - 30) % 3] }
}

export function writeSoundtrack(path, seconds = 66) {
  const n = Math.round(seconds * SR)
  const L = new Float32Array(n), R = new Float32Array(n)
  let seed = 12345
  const rnd = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296) * 2 - 1

  const add = (i, v, pan = 0) => { if (i >= 0 && i < n) { L[i] += v * (1 - Math.max(0, pan)); R[i] += v * (1 + Math.min(0, pan)) } }
  const osc = (type, ph) => {
    const x = ph % 1
    return type === 'sine' ? Math.sin(2 * Math.PI * x) : type === 'saw' ? 2 * x - 1 : type === 'square' ? (x < 0.5 ? 1 : -1) : 1 - 4 * Math.abs(x - 0.5)
  }

  /** Oscillator voice with an attack/release envelope, optional pitch glide and a one-pole lowpass. */
  function voice(t0, dur, freq, { type = 'saw', gain = 0.1, a = 0.01, r = 0.2, cutoff = 4000, pan = 0, detune = 0, to = null, vib = 0 } = {}) {
    const s0 = Math.round(t0 * SR), len = Math.round((dur + r) * SR)
    let lp = 0, ph1 = 0, ph2 = 0
    const k = 1 - Math.exp((-2 * Math.PI * cutoff) / SR)
    for (let j = 0; j < len; j++) {
      const t = j / SR
      const env = Math.min(1, t / a) * (t < dur ? 1 : Math.max(0, 1 - (t - dur) / r))
      const f = (to ? freq * (to / freq) ** Math.min(1, t / dur) : freq) * (1 + vib * Math.sin(2 * Math.PI * 6 * t))
      ph1 += f / SR; ph2 += (f * (1 + detune)) / SR
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
  /** A bell: two sine partials with a long decay. */
  const bell = (t0, f, gain = 0.12) => { voice(t0, 0.02, f, { type: 'sine', gain, a: 0.002, r: 1.2 }); voice(t0, 0.02, f * 2.76, { type: 'sine', gain: gain * 0.35, a: 0.002, r: 0.5 }) }

  const bars = Math.ceil(seconds / BAR)
  for (let b = 0; b < bars; b++) {
    const t0 = b * BAR, { sec, ch } = bar(b), [bass, chord] = CH[ch]
    // pad
    const padGain = { intro: 0.05, groove: 0.03, data: 0.045, play: 0.03, sad: 0.07, hope: 0.05, happy: 0.035, outro: 0.05 }[sec]
    const padCut = sec === 'intro' ? 900 + 300 * b : sec === 'data' ? 700 + 1600 * ((b - 12) / 4) : sec === 'sad' ? 800 : 1400
    for (const [i, f] of chord.entries()) voice(t0, BAR, f, { type: 'saw', gain: padGain, a: 0.3, r: 0.6, cutoff: padCut, detune: 0.006, pan: (i - 1) * 0.5 })

    if (sec === 'groove' || sec === 'happy') {
      for (let q = 0; q < 8; q++) {
        const t = t0 + q * BEAT / 2
        voice(t, BEAT / 2 * 0.8, q % 2 ? bass * 2 : bass, { type: 'square', gain: 0.11, a: 0.004, r: 0.05, cutoff: 600 })
        const note = chord[[0, 1, 2, 1, 2, 0, 1, 2][q]] * 2
        voice(t, 0.09, note, { type: 'triangle', gain: 0.075, a: 0.002, r: 0.25, cutoff: 5000, pan: q % 2 ? 0.35 : -0.35 })
        if (q % 2 === 0) kick(t)
        if (q % 2 === 1) noiseHit(t, 0.06, { gain: 0.12, hp: 7000, decay: 60, pan: 0.2 })
        if (q === 2 || q === 6) noiseHit(t, 0.22, { gain: 0.32, hp: 900, lp: 6000, decay: 18 })
      }
      for (let s = 8; s < 16; s++) noiseHit(t0 + s * BEAT / 4, 0.03, { gain: 0.05, hp: 9000, decay: 90, pan: -0.25 })
    } else if (sec === 'data') {
      // half time: kick on 1, clap on 3, a sparkling 16th arpeggio for the data stream
      kick(t0); kick(t0 + 3 * BEAT / 2, 0.5); noiseHit(t0 + 2 * BEAT, 0.3, { gain: 0.26, hp: 1200, lp: 7000, decay: 12 })
      voice(t0, BAR * 0.95, bass, { type: 'sine', gain: 0.16, a: 0.02, r: 0.2 })
      for (let s = 0; s < 16; s++) {
        const f = chord[s % 3] * (s % 6 < 3 ? 4 : 2)
        voice(t0 + s * BEAT / 4, 0.05, f, { type: 'sine', gain: 0.045, a: 0.002, r: 0.18, pan: Math.sin(s) * 0.6 })
      }
    } else if (sec === 'play') {
      // oom-pah: bass on 1 and 3, chord stabs on 2 and 4, a bouncy pluck tune, woodblock ticks
      for (let q = 0; q < 4; q++) {
        const t = t0 + q * BEAT
        if (q % 2 === 0) { kick(t, 0.5); voice(t, 0.18, q === 0 ? bass : bass * 1.5, { type: 'triangle', gain: 0.32, a: 0.003, r: 0.08, cutoff: 1200 }) }
        else for (const f of chord) voice(t, 0.08, f, { type: 'square', gain: 0.05, a: 0.002, r: 0.06, cutoff: 2500 })
        voice(t + BEAT / 2, 0.02, 1800, { type: 'sine', gain: 0.1, a: 0.001, r: 0.04 })
      }
      const tune = [[0, 2], [0.5, 1], [1, 0], [1.5, 1], [2, 2], [2.75, 2], [3, 2]]
      for (const [beat, k] of tune) voice(t0 + beat * BEAT, 0.12, chord[k] * 2, { type: 'triangle', gain: 0.16, a: 0.003, r: 0.2, cutoff: 5000, pan: 0.2 })
    } else if (sec === 'sad') {
      // slow, sparse: a falling sine melody over the pad
      voice(t0, BAR * 0.95, bass, { type: 'sine', gain: 0.24, a: 0.1, r: 0.4 })
      const mel = ch === 'Am' ? [N.E5, N.C5, N.A4] : [N.F4 * 2, N.D4 * 2, N.A4]
      mel.forEach((f, i) => voice(t0 + i * 0.6, 0.45, f, { type: 'sine', gain: 0.14, a: 0.04, r: 0.5, vib: 0.006 }))
    } else if (sec === 'hope') {
      for (let q = 0; q < 8; q++) {
        const t = t0 + q * BEAT / 2
        voice(t, BEAT / 2 * 0.7, bass, { type: 'square', gain: 0.11, a: 0.004, r: 0.05, cutoff: 500 })
        voice(t, 0.08, chord[q % 3] * 2, { type: 'triangle', gain: 0.09, a: 0.002, r: 0.2, cutoff: 5000, pan: q % 2 ? 0.3 : -0.3 })
        if (q % 2 === 0) kick(t, 0.75)
        if (q % 2 === 1) noiseHit(t, 0.05, { gain: 0.1, hp: 7000, decay: 60 })
      }
    }
  }
  // intro: logo shimmer and a riser into the first cut
  whoosh(4, 1.6, 0.25)
  for (let i = 0; i < 6; i++) voice(0.25 + i * 0.12, 0.25, [659.25, 783.99, 880, 987.77, 1174.66, 1318.51][i], { type: 'sine', gain: 0.05, a: 0.005, r: 0.6, pan: i % 2 ? 0.5 : -0.5 })
  for (const c of CUTS) whoosh(c)
  whoosh(32, 2.0, 0.22) // build out of the data break
  // two-neighbours story effects
  voice(39.45, 0.12, 800, { type: 'sine', gain: 0.08, to: 1200, r: 0.05 })           // the risk card pops up
  bell(40.0, 659.25, 0.06); bell(40.45, 987.77, 0.08); bell(40.7, 1318.51, 0.08)      // corn high, wheat low, tick
  noiseHit(41.6, 0.25, { gain: 0.12, lp: 1500, decay: 12 })                          // "pfft": the neighbour shrugs it off
  voice(42.25, 0.35, 500, { type: 'sine', gain: 0.08, to: 300, r: 0.05 })            // wheat seed toss
  voice(42.64, 0.12, 600, { type: 'sine', gain: 0.12, to: 1300, r: 0.05 })           // wheat sprout pop
  voice(43.12, 0.9, 180, { type: 'sine', gain: 0.14, to: 900, vib: 0.04, r: 0.1 })   // boing: the wheat shoots up
  voice(43.37, 0.35, 700, { type: 'triangle', gain: 0.08, to: 1400, r: 0.05 })      // the farmer's surprise
  noiseHit(43.37, 0.15, { gain: 0.15, hp: 2000, decay: 25 })
  voice(45.77, 0.35, 500, { type: 'sine', gain: 0.08, to: 300, r: 0.05 })            // corn seed toss
  voice(46.16, 0.12, 600, { type: 'sine', gain: 0.12, to: 1300, r: 0.05 })           // corn sprout pop
  voice(46.85, 0.6, 220, { type: 'sine', gain: 0.1, to: 700, r: 0.1 })               // the corn grows
  for (const [i, f] of [392, 370, 349.23, 311.13].entries())                         // wah-wah: the corn falls ill
    voice(48.0 + i * 0.32, i === 3 ? 0.8 : 0.26, f, { type: 'saw', gain: 0.07, cutoff: 900, a: 0.02, r: 0.1, vib: i === 3 ? 0.02 : 0, to: i === 3 ? f * 0.94 : null })
  voice(49.4, 1.4, 600, { type: 'sine', gain: 0.04, to: 1400, r: 0.05 })             // the fever rises
  noiseHit(50.8, 0.15, { gain: 0.15, hp: 2000, decay: 25 })                          // the neighbour's shock
  bell(53.45, 1567.98, 0.1)                                                          // light bulb: he listens
  bell(55.85, 1318.51, 0.14); bell(55.97, 1975.53, 0.1)                              // "ding": order placed
  kick(57.75, 0.8); noiseHit(57.75, 0.2, { gain: 0.2, lp: 1500, decay: 20 })          // the parcel lands
  for (let i = 0; i < 8; i++) voice(57.7 + i * 0.07, 0.2, [N.C5, N.E5, N.G5, 1046.5, 1318.51, 1567.98, 2093, 2637][i], { type: 'sine', gain: 0.05, a: 0.003, r: 0.4, pan: i % 2 ? 0.5 : -0.5 })
  for (const f of [N.C4, N.E4, N.G4, N.C5]) voice(58, 1.8, f, { type: 'saw', gain: 0.03, a: 0.02, r: 0.3, cutoff: 2600, detune: 0.004 })
  // end card: impact and a closing chord
  kick(60, 1.1); noiseHit(60, 1.6, { gain: 0.22, hp: 3000, decay: 2.5 })
  for (const f of [110, 220, 261.63, 329.63, 440]) voice(63.5, 2.0, f, { type: 'saw', gain: 0.04, a: 0.02, r: 0.4, cutoff: 1800, detune: 0.005 })

  // master: soft clip, normalise to -1 dBFS, fade the last second
  let peak = 0
  for (let i = 0; i < n; i++) { L[i] = Math.tanh(L[i] * 1.2); R[i] = Math.tanh(R[i] * 1.2); peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i])) }
  const g = 0.89 / peak, fadeFrom = n - 1.0 * SR
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
