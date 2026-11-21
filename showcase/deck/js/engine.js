// Glue between reveal.js (navigation) and GSAP (animation).
//
// A slide opts in with  <section data-anim="name">  and a builder registered with
//   Deck.anim('name', (slide, Deck) => timeline)
// The builder runs inside a gsap.context scoped to the slide each time the slide is entered,
// and everything it animates is reverted after the slide is left, so every visit starts fresh.
//
// Steps: put empty  <i class="fragment step"></i>  markers in the slide (one per click) and add
// labels "step1", "step2", ... to the timeline. Entering the slide plays from 0 to "step1";
// each click plays to the next label (the last one plays to the end); going back rewinds.
// A slide without step markers simply plays its whole timeline on entry.
//
// Extra keys: R replays the current slide's animation.
;(function () {
  'use strict'
  gsap.registerPlugin(SplitText, DrawSVGPlugin, MotionPathPlugin, Flip, Draggable)

  const registry = Object.create(null)
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const retiring = new Map() // slide -> { ctx, timer }
  let active = null // { slide, ctx, tl, nav }

  const Deck = (window.Deck = {
    reduced,
    anim(name, build) {
      registry[name] = build
    },
    /** Path of a GUI screenshot from capture.mjs. */
    shot: (name) => `../shots/${name}.png`,
    /** [x, y, w, h] of a captured element in screenshot pixels (2400 x 1350). */
    rect(shot, key, i = 0) {
      const r = window.RECTS?.[shot]?.[key]?.[i]
      if (!r) console.warn(`[deck] no rect for ${shot}.${key}[${i}]; re-run capture.mjs?`)
      return r ?? null
    },
    /** Size of an element in slide pixels (unaffected by reveal's scaling). */
    size(el) {
      const cs = getComputedStyle(el)
      return { w: parseFloat(cs.width), h: parseFloat(cs.height) }
    },
    /** Run DOM construction once per slide, however often the slide is visited. */
    once(slide, key, fn) {
      const flag = `built${key}`
      if (slide.dataset[flag]) return
      slide.dataset[flag] = '1'
      fn()
    },
    /** A tween that counts an element's text from 0 to `to`. */
    countUp(el, to, vars = {}) {
      const o = { v: 0 }
      el.textContent = '0'
      return gsap.to(o, {
        v: to,
        duration: 1.4,
        ease: 'power2.out',
        ...vars,
        onUpdate: () => (el.textContent = Math.round(o.v).toLocaleString('en-US')),
      })
    },
    /** Endless decorative motion: skipped when the viewer prefers reduced motion. */
    loop(fn) {
      return reduced ? null : fn()
    },
  })

  // ---------- step navigation ----------
  const stepsShown = (slide) => slide.querySelectorAll('.fragment.step.visible').length
  function stepTime(tl, shown) {
    const t = tl.labels[`step${shown + 1}`]
    return t === undefined ? tl.duration() : t
  }
  function seekStep(instant = false) {
    if (!active?.tl) return
    const { tl, slide } = active
    const target = stepTime(tl, stepsShown(slide))
    active.nav?.kill()
    if (instant || reduced) {
      tl.pause(target)
      return
    }
    const back = target < tl.time()
    active.nav = back ? tl.tweenTo(target, { duration: Math.min(0.6, tl.time() - target), ease: 'power2.inOut' }) : tl.tweenTo(target)
  }

  // ---------- slide lifecycle ----------
  function revertNow(slide) {
    const r = retiring.get(slide)
    if (!r) return
    clearTimeout(r.timer)
    r.ctx.revert()
    retiring.delete(slide)
  }
  function retire(a) {
    a.nav?.kill()
    a.slide.querySelectorAll('video').forEach((v) => v.pause())
    // Keep the outgoing slide in its final state while reveal fades it out, then reset it.
    const timer = setTimeout(() => revertNow(a.slide), 1000)
    retiring.set(a.slide, { ctx: a.ctx, timer })
  }
  function build(slide) {
    const fn = registry[slide.dataset.anim]
    if (!fn) {
      console.warn(`[deck] no animation registered as "${slide.dataset.anim}"`)
      return null
    }
    let tl = null
    const ctx = gsap.context(() => {
      tl = fn(slide, Deck) || null
    }, slide)
    tl?.pause(0)
    return { slide, ctx, tl, nav: null }
  }
  function enter(slide, instant = false) {
    if (active) {
      if (active.slide === slide) {
        active.nav?.kill()
        active.ctx.revert()
      } else retire(active)
    }
    active = null
    if (!slide?.dataset.anim) return
    revertNow(slide)
    active = build(slide)
    seekStep(instant)
  }

  // ---------- PDF export (?print-pdf): show every slide in its final state ----------
  function printAll() {
    document.querySelectorAll('.reveal .slides section[data-anim]').forEach((slide) => {
      const a = build(slide)
      if (!a?.tl) return
      a.tl.pause(a.tl.labels.print ?? a.tl.duration())
    })
  }

  // ---------- background drift ----------
  function driftBackground() {
    Deck.loop(() =>
      gsap.utils.toArray('#bg .blob').forEach((b, i) =>
        gsap.to(b, {
          x: gsap.utils.random(-160, 160),
          y: gsap.utils.random(-120, 120),
          scale: gsap.utils.random(0.85, 1.2),
          duration: 14 + i * 3,
          ease: 'sine.inOut',
          repeat: -1,
          yoyo: true,
        }),
      ),
    )
  }

  // ---------- wiring ----------
  Deck.start = function (config = {}) {
    Reveal.initialize({
      width: 1920,
      height: 1080,
      margin: 0,
      minScale: 0.1,
      maxScale: 4,
      center: false,
      hash: true,
      controls: true,
      controlsTutorial: false,
      progress: true,
      transition: 'fade',
      transitionSpeed: 'fast',
      backgroundTransition: 'none',
      pdfSeparateFragments: false,
      plugins: [RevealNotes],
      ...config,
    })
    Reveal.on('ready', (e) => {
      // reveal.js 6 renamed isPrintingPDF() to isPrintView(); support both.
      const printing = Reveal.isPrintView?.() ?? Reveal.isPrintingPDF?.() ?? false
      if (printing) return printAll()
      driftBackground()
      enter(e.currentSlide, true)
    })
    Reveal.on('slidechanged', (e) => {
      const from = e.previousSlide ? Reveal.getIndices(e.previousSlide) : null
      const to = Reveal.getIndices(e.currentSlide)
      // Arriving backwards shows all fragments at once: jump straight to the end state.
      const backwards = from && (from.h > to.h || (from.h === to.h && from.v > to.v))
      enter(e.currentSlide, backwards)
    })
    const onFragment = (e) => {
      if (active && active.slide.contains(e.fragment)) seekStep()
    }
    Reveal.on('fragmentshown', onFragment)
    Reveal.on('fragmenthidden', onFragment)
    Reveal.addKeyBinding({ keyCode: 82, key: 'R', description: 'Replay slide animation' }, () =>
      enter(Reveal.getCurrentSlide()),
    )
  }
})()
