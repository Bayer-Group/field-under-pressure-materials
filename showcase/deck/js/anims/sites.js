// "Two sites, 29 plots": site cards slide in, then one dot per plot drops in and the total counts up.
// Steps: 1 plots drop + counter.
Deck.anim('sites', (slide, D) => {
  const wrap = slide.querySelector('.sites')
  Deck.once(slide, 'sites', () => {
    DeckData.sites.forEach((s) => {
      const card = document.createElement('div')
      card.className = 'site-card'
      card.innerHTML = `
        <div class="site-code">${s.code}</div>
        <div class="site-name">${s.name}</div>
        <div class="site-meta">${s.plots} plots · ${s.tag}</div>
        <div class="plots">${'<i></i>'.repeat(s.plots)}</div>`
      wrap.append(card)
    })
    const total = DeckData.sites.reduce((n, s) => n + s.plots, 0)
    slide.querySelector('.total .n').dataset.to = total
  })

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(slide.querySelectorAll('.kicker, .heading'), { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 })
    .from(wrap.children, { y: 80, autoAlpha: 0, duration: 0.8, stagger: 0.15 }, '-=0.3')

  tl.addLabel('step1')
    .from(wrap.querySelectorAll('.plots i'), {
      y: -90,
      autoAlpha: 0,
      duration: 0.7,
      ease: 'bounce.out',
      stagger: { each: 0.035, from: 'random' },
    })
    .from(slide.querySelector('.total'), { scale: 0.6, autoAlpha: 0, duration: 0.6, ease: 'back.out(2)' }, 'step1')
  const n = slide.querySelector('.total .n')
  tl.add(D.countUp(n, +n.dataset.to, { duration: 1.2 }), 'step1')
  return tl
})
