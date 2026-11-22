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
