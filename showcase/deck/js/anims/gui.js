// Generic "tour of a real GUI screen": a browser window with a screenshot from capture.mjs that
// zooms onto captured elements, one per click. Reusable on any slide:
//
//   <section data-anim="gui">
//     <div class="win"><div class="bar">…</div><div class="vp"><img data-shot="overview"></div></div>
//     <i class="fragment step" data-focus="site:0" data-caption="North Sterling: 19 plots"></i>
//     <i class="fragment step" data-focus="map" data-caption="…"></i>
//     <i class="fragment step" data-focus="all"></i>        ← zoom back out
//   </section>
//
// data-focus is "<rect key>:<index>" from shots/rects.json for that shot ("all" = whole screen).
// Optional data-pad (screenshot px around the element, default 40).
const SHOT_W = 2400, SHOT_H = 1350

Deck.anim('gui', (slide) => {
  const win = slide.querySelector('.win')
  const vp = win.querySelector('.vp')
  const img = vp.querySelector('img')
  const shot = img.dataset.shot
  const { w: vw, h: vh } = Deck.size(vp)
  const base = vw / SHOT_W

  function focus(spec, pad) {
    if (!spec || spec === 'all') return { x: 0, y: 0, scale: base }
    const [key, i = 0] = spec.split(':')
    const r = Deck.rect(shot, key, +i)
    if (!r) return { x: 0, y: 0, scale: base }
    const [rx, ry, rw, rh] = r
    const s = Math.max(base, Math.min(vw / (rw + 2 * pad), vh / (rh + 2 * pad)))
    const clamp = (v, lo) => Math.min(0, Math.max(lo, v))
    return {
      scale: s,
      x: clamp(vw / 2 - (rx + rw / 2) * s, vw - SHOT_W * s),
      y: clamp(vh / 2 - (ry + rh / 2) * s, vh - SHOT_H * s),
    }
  }

  const steps = [...slide.querySelectorAll('.fragment.step')]
  Deck.once(slide, 'gui', () => {
    img.src = Deck.shot(shot)
    steps.forEach((st) => {
      if (!st.dataset.caption) return
      const pill = document.createElement('div')
      pill.className = 'pill gui-caption'
      pill.innerHTML = st.dataset.caption
      slide.append(pill)
      st._pill = pill
    })
  })

  gsap.set(img, { transformOrigin: '0 0', ...focus('all') })
  gsap.set(slide.querySelectorAll('.gui-caption'), { autoAlpha: 0 })

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(slide.querySelectorAll('.kicker, .heading, .sub'), { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 })
    .from(win, { y: 160, rotateX: 14, transformPerspective: 1800, transformOrigin: '50% 0%', autoAlpha: 0, duration: 1.1 }, 0.15)
  tl.addLabel('print')

  let prevPill = null
  steps.forEach((st, k) => {
    const at = `step${k + 1}`
    tl.addLabel(at)
      .to(img, { ...focus(st.dataset.focus, +(st.dataset.pad ?? 40)), duration: 1.2, ease: 'power3.inOut' }, at)
    if (prevPill) tl.to(prevPill, { autoAlpha: 0, y: 10, duration: 0.3 }, at)
    if (st._pill) tl.fromTo(st._pill, { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, duration: 0.5 }, `${at}+=0.7`)
    prevPill = st._pill ?? null
  })
  return tl
})
