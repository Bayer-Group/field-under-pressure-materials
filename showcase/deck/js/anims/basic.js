// Small reusable animations for text-only slides.

// Title: the letters wipe in while the Earth slides into the "o" spinning fast, then settles into
// a slow endless turn.
Deck.anim('title', (slide, D) => {
  const { letters, globe } = D.lockup(slide.querySelector('.lockup'))
  const earth = D.earth(globe)
  const spin = D.loop(() => gsap.to(earth, { lon: '-=360', duration: 36, ease: 'none', repeat: -1, onUpdate: earth.draw }))
  const tl = gsap.timeline()
  tl.fromTo(letters, { clipPath: 'inset(0% 100% 0% 0%)' }, { clipPath: 'inset(0% 0% 0% 0%)', duration: 1.4, ease: 'power3.inOut' }, 0.1)
    .from(globe, { x: 700, scale: 0.4, autoAlpha: 0, duration: 1.6, ease: 'power3.out' }, 0.3)
  if (spin) tl.fromTo(spin, { timeScale: 16 }, { timeScale: 1, duration: 3, ease: 'power2.out' }, 0.3)
  return tl
})

// Generic text slide: heading words slide up, then every .rise element follows.
// Use it on any slide with  data-anim="text".
Deck.anim('text', (slide) => {
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  const head = slide.querySelector('.heading')
  if (head) {
    const split = SplitText.create(head, { type: 'words', mask: 'words' })
    tl.from(split.words, { yPercent: 110, duration: 0.8, stagger: 0.06 })
  }
  tl.from(slide.querySelectorAll('.kicker'), { x: -30, autoAlpha: 0, duration: 0.6 }, 0)
  const rise = slide.querySelectorAll('.rise')
  if (rise.length) tl.from(rise, { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 }, '-=0.4')
  return tl
})

// Outro: logo builds, words rise, numbers count up.
Deck.anim('outro', (slide, D) => {
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  const split = SplitText.create(slide.querySelector('.heading'), { type: 'words', mask: 'words' })
  tl.add(D.lockupIn(slide.querySelector('.lockup')))
    .from(split.words, { yPercent: 110, duration: 0.9, stagger: 0.08 }, '-=0.6')
    .from(slide.querySelectorAll('.stat'), { y: 60, autoAlpha: 0, duration: 0.7, stagger: 0.12 }, '-=0.3')
  slide.querySelectorAll('.stat .n[data-to]').forEach((n, i) => {
    tl.add(D.countUp(n, +n.dataset.to), `<+=${i * 0.04}`)
  })
  tl.from(slide.querySelectorAll('.rise'), { autoAlpha: 0, y: 20, duration: 0.6 }, '-=0.6')
  return tl
})
