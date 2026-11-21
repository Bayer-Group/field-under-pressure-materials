import { useEffect, useRef, useState, type CSSProperties } from 'react'
import './landing.css'

// Landing screen: the Terranos logo builds the way it does in the showcase video (showcase/video.html):
// the letters wipe in and the globe rolls into the "o". Pure CSS animation; this component only lays it out
// and runs the exit wipe. Shown once, on a fresh load of the overview; deep links go straight to the app.

/** Globe position inside the wordmark, copied from showcase/brand/logo.js (written by scripts/make_brand_assets.py). */
const LOGO = { x: 0.7917, y: 0.5771, d: 0.1474, aspect: 0.1797 }
/** Same roll as the video: 640 px at a 1100 px wide wordmark, one full rotation per globe circumference. */
const ROLL = 640 / 1100
const TURNS = ROLL / (Math.PI * LOGO.d)

/** The video's tagline, word by word; the second half is highlighted. */
const TAGLINE: [string, boolean][] = [['Your', false], ['fields,', false], ['from', true], ['orbit', true], ['to', true], ['the', true], ['microbe.', true]]
const FEATURES: [string, string][] = [
  ['#3fae6a', 'Satellite greenness'], ['#60a5fa', 'Aerial photos'], ['#fbbf24', 'Soil microbes'],
  ['#b5f26b', 'Soil characteristics'], ['#f87171', 'Crop disease risk'], ['#ea580c', 'Treatment plan'],
]

/** Deterministic pseudo-random numbers, so the grass and soil look the same on every load. */
function rng(seed: number) { return () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296) }

const GROUND = (() => {
  const r = rng(7), GY = 70
  const blades = Array.from({ length: 200 }, (_, i) => {
    const x = i * 9.8 - 10 + r() * 8, h = 22 + r() * 40, lean = (r() - 0.5) * 18
    return { d: `M ${x.toFixed(1)} ${GY + 2} q ${(lean * 0.4).toFixed(1)} ${(-h * 0.6).toFixed(1)} ${lean.toFixed(1)} ${(-h).toFixed(1)}`,
      color: r() < 0.5 ? '#2f9e5a' : '#5cc97f', delay: -(r() * 3).toFixed(2) }
  })
  const strata = Array.from({ length: 3 }, (_, i) => {
    const y = GY + 60 + i * 60
    let d = `M -20 ${y}`
    for (let x = -20; x < 1940; x += 160) d += ` Q ${x + 80} ${(y + (r() - 0.5) * 30).toFixed(0)} ${x + 160} ${y}`
    return d
  })
  const pebbles = Array.from({ length: 60 }, () => ({ cx: r() * 1920, cy: GY + 25 + r() * 220, rx: 4 + r() * 12, ry: 3 + r() * 8, fill: r() < 0.5 ? '#7d5c40' : '#5a4130' }))
  const microbes = Array.from({ length: 70 }, () => ({ cx: r() * 1920, cy: GY + 30 + r() * 220, r: 2 + r() * 3.5,
    fill: ['#b5f26b', '#fbbf24', '#7dd3fc'][Math.floor(r() * 3)], delay: -(r() * 4).toFixed(2), dur: (2.5 + r() * 2.5).toFixed(2) }))
  return { GY, blades, strata, pebbles, microbes }
})()

const reducedMotion = () => typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** True when the page was opened on the overview (no deep link), the only time the landing screen is shown. */
export function landingWanted(): boolean {
  return /^#?\/?$/.test(window.location.hash)
}

type Phase = 'show' | 'leaving' | 'revealed'

/** onDone is called once the exit wipe has finished; the parent then unmounts the landing screen. */
export function Landing({ onDone }: { onDone: () => void }) {
  const [phase, setPhase] = useState<Phase>('show')
  const dialog = useRef<HTMLDivElement>(null)
  const dismiss = () => setPhase((p) => (p === 'show' ? 'leaving' : p))

  // Keyboard: Enter, Space or Escape enter the app; navigating elsewhere (e.g. Back) does too.
  useEffect(() => {
    if (phase !== 'show') return
    dialog.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Escape') { e.preventDefault(); dismiss() }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('hashchange', dismiss)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('hashchange', dismiss) }
  }, [phase])

  // Exit: a diagonal wipe sweeps across; the landing content is dropped while the wipe covers the screen.
  useEffect(() => {
    if (phase !== 'leaving' && phase !== 'revealed') return
    const quick = reducedMotion()
    const id = phase === 'leaving'
      ? window.setTimeout(() => setPhase('revealed'), quick ? 0 : 380)
      : window.setTimeout(onDone, quick ? 0 : 420)
    return () => window.clearTimeout(id)
  }, [phase, onDone])

  const globeStyle: CSSProperties = {
    left: `${(LOGO.x - LOGO.d / 2) * 100}%`,
    top: `${(LOGO.y - LOGO.d / (2 * LOGO.aspect)) * 100}%`,
    width: `${LOGO.d * 100}%`,
    ['--roll' as string]: `${(ROLL / LOGO.d) * 100}%`,
    ['--turns' as string]: `${TURNS * 360}deg`,
  }
  const base = import.meta.env.BASE_URL
  return (
    <div className={`landing ${phase}`} role="dialog" aria-modal="true" aria-label="Welcome to Terranos" ref={dialog} tabIndex={-1}>
      {phase !== 'revealed' && (
        <div className="landing-scene">
          <div className="landing-bg" aria-hidden="true">
            <div className="landing-blob a" />
            <div className="landing-blob b" />
            <div className="landing-dots" />
          </div>
          <svg className="landing-ground" viewBox="0 0 1920 330" preserveAspectRatio="xMidYMin slice" aria-hidden="true">
            <defs>
              <linearGradient id="landing-soil" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#6b4528" /><stop offset=".45" stopColor="#4a2f1b" /><stop offset="1" stopColor="#1e1209" />
              </linearGradient>
            </defs>
            <rect x="-20" y={GROUND.GY} width="1960" height="300" fill="url(#landing-soil)" />
            {GROUND.strata.map((d, i) => <path key={i} d={d} fill="none" stroke="rgba(0,0,0,.28)" strokeWidth="3" />)}
            {GROUND.pebbles.map((p, i) => <ellipse key={i} {...p} />)}
            {GROUND.microbes.map((m, i) => (
              <circle key={i} className="landing-microbe" cx={m.cx} cy={m.cy} r={m.r} fill={m.fill}
                style={{ animationDelay: `${m.delay}s`, animationDuration: `${m.dur}s` }} />
            ))}
            {GROUND.blades.map((b, i) => (
              <path key={i} className="landing-blade" d={b.d} stroke={b.color} strokeWidth="4" strokeLinecap="round" fill="none"
                style={{ animationDelay: `${b.delay}s` }} />
            ))}
          </svg>
          <div className="landing-vignette" aria-hidden="true" />

          <div className="landing-content">
            <h1 className="landing-lockup">
              <img className="landing-letters" src={`${base}terranos-dark-letters.png`} alt="Terranos" draggable={false} />
              <img className="landing-globe" src={`${base}terranos-globe.png`} alt="" style={globeStyle} draggable={false} />
            </h1>
            <p className="landing-tagline">
              {TAGLINE.map(([word, hl], i) => (
                <span key={i} className="landing-mask">
                  <span className={hl ? 'hl' : undefined} style={{ animationDelay: `${1.0 + i * 0.06}s` }}>{word}</span>
                </span>
              ))}
            </p>
            <ul className="landing-tags" aria-label="What you can explore">
              {FEATURES.map(([c, label], i) => (
                <li key={label} style={{ animationDelay: `${1.55 + i * 0.1}s` }}>
                  <span className="landing-dot" style={{ background: c, boxShadow: `0 0 12px ${c}` }} />{label}
                </li>
              ))}
            </ul>
            <div className="landing-cta">
              <button type="button" onClick={dismiss}>Explore the plots <span aria-hidden="true">→</span></button>
              <span className="landing-hint">or press Enter</span>
            </div>
          </div>
        </div>
      )}
      {phase !== 'show' && <div className="landing-wipe" aria-hidden="true"><div className="edge" /></div>}
    </div>
  )
}
