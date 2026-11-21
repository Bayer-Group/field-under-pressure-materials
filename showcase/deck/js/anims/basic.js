// Small reusable animations for text-only slides.

// Title: the leaf draws itself, the title rises letter by letter, the rest follows.
Deck.anim('title', (slide) => {
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  const title = SplitText.create(slide.querySelector('.title'), { type: 'chars', mask: 'chars' })
  tl.from(slide.querySelectorAll('.leaf path'), { drawSVG: 0, duration: 1.3, ease: 'power2.inOut', stagger: 0.2 })
    .from(title.chars, { yPercent: 115, duration: 0.9, stagger: 0.035 }, 0.25)
    .from(slide.querySelectorAll('.rise'), { y: 40, autoAlpha: 0, duration: 0.8, stagger: 0.12 }, '-=0.45')
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

// Outro: words rise, numbers count up.
Deck.anim('outro', (slide, D) => {
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  const split = SplitText.create(slide.querySelector('.heading'), { type: 'words', mask: 'words' })
  tl.from(split.words, { yPercent: 110, duration: 0.9, stagger: 0.08 })
    .from(slide.querySelectorAll('.stat'), { y: 60, autoAlpha: 0, duration: 0.7, stagger: 0.12 }, '-=0.3')
  slide.querySelectorAll('.stat .n[data-to]').forEach((n, i) => {
    tl.add(D.countUp(n, +n.dataset.to), `<+=${i * 0.04}`)
  })
  tl.from(slide.querySelectorAll('.rise'), { autoAlpha: 0, y: 20, duration: 0.6 }, '-=0.6')
  return tl
})
