// "Everything links to the sampling event": data sources on a ring, lines draw into the hub.
// Steps: 1 sources appear · 2 lines draw and the hub lands · 3 caption.
Deck.anim('sources', (slide) => {
  const stage = slide.querySelector('.hub-stage')
  const { w, h } = Deck.size(stage)
  const cx = w / 2, cy = h / 2, rx = w * 0.39, ry = h * 0.4

  Deck.once(slide, 'sources', () => {
    const svg = stage.querySelector('svg')
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
    DeckData.sources.forEach((s, i, all) => {
      const a = (-90 + (360 / all.length) * i) * (Math.PI / 180)
      const x = cx + Math.cos(a) * rx, y = cy + Math.sin(a) * ry
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'path')
      line.setAttribute('d', `M${x},${y} L${cx},${cy}`)
      line.setAttribute('class', 'link')
      const pulse = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
      pulse.setAttribute('r', 9)
      pulse.setAttribute('class', 'pulse')
      svg.append(line, pulse)
      const chip = document.createElement('div')
      chip.className = 'src'
      chip.style.left = `${x}px`
      chip.style.top = `${y}px`
      chip.innerHTML = `<b>${s.name}</b><span>${s.what}</span>`
      stage.append(chip)
    })
  })

  const chips = stage.querySelectorAll('.src')
  const links = stage.querySelectorAll('.link')
  const pulses = stage.querySelectorAll('.pulse')
  const hub = stage.querySelector('.hub')

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(slide.querySelectorAll('.kicker, .heading'), { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 })
  gsap.set(pulses, { autoAlpha: 0 })

  tl.addLabel('step1')
    .from(chips, { scale: 0.5, autoAlpha: 0, duration: 0.6, ease: 'back.out(1.8)', stagger: { each: 0.07, from: 'random' } })

  tl.addLabel('step2')
    .from(links, { drawSVG: 0, duration: 0.9, ease: 'power2.inOut', stagger: 0.05 })
  pulses.forEach((p, i) => {
    tl.set(p, { autoAlpha: 1 }, `step2+=${0.25 + i * 0.05}`)
      .to(p, { motionPath: { path: links[i], align: links[i], alignOrigin: [0.5, 0.5] }, duration: 0.8, ease: 'power1.in' }, '<')
      .set(p, { autoAlpha: 0 })
  })
  tl.from(hub, { scale: 0, autoAlpha: 0, duration: 0.8, ease: 'back.out(2)' }, 'step2+=1')
    .to(chips, { borderColor: 'rgba(181,242,107,.6)', duration: 0.4, stagger: 0.03 }, '<')

  tl.addLabel('step3')
    .from(slide.querySelectorAll('.caption'), { y: 30, autoAlpha: 0, duration: 0.6 })

  // Hub breathing (decorative, independent of the step timeline)
  Deck.loop(() => gsap.to(hub.querySelector('.ring'), { scale: 1.25, autoAlpha: 0, duration: 1.8, repeat: -1, ease: 'power1.out' }))
  return tl
})
