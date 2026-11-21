// "Greenness over time": an SVG chart that builds itself from DeckData.greenness.
// Steps: 1 satellite readings pop in · 2 the season curve draws · 3 sampling visits drop in.
Deck.anim('greenness', (slide) => {
  const svg = slide.querySelector('svg.chart')
  const W = 1500, H = 600, L = 90, R = 30, T = 40, B = 70
  const G = DeckData.greenness
  const x = (d) => L + ((d - G.dayRange[0]) / (G.dayRange[1] - G.dayRange[0])) * (W - L - R)
  const y = (v) => H - B - v * (H - T - B)

  Deck.once(slide, 'chart', () => {
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`)
    const months = [['Apr', 91], ['May', 121], ['Jun', 152], ['Jul', 182], ['Aug', 213], ['Sep', 244], ['Oct', 274]]
    let s = '<g class="axis">'
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 16}" y="${y(v) + 7}" text-anchor="end">${v}</text>`
    }
    for (const [m, d] of months) s += `<text x="${x(d)}" y="${H - B + 42}" text-anchor="middle">${m}</text>`
    s += '</g>'
    let path = ''
    for (let d = G.dayRange[0]; d <= G.dayRange[1]; d += 2) path += `${path ? 'L' : 'M'}${x(d).toFixed(1)},${y(G.curve(d)).toFixed(1)}`
    s += `<path class="curve" d="${path}"/>`
    s += '<g class="readings">' + G.readings.map((r) => `<circle cx="${x(r.day)}" cy="${y(r.ndvi)}" r="8"/>`).join('') + '</g>'
    s += '<g class="visits">' + G.visits.map((d) =>
      `<g class="visit" transform="translate(${x(d)},0)"><line y1="${T - 10}" y2="${H - B}"/><rect x="-11" y="${T - 22}" width="22" height="22" transform="rotate(45 0 ${T - 11})"/></g>`).join('') + '</g>'
    svg.innerHTML = s
  })

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(slide.querySelectorAll('.kicker, .heading, .sub'), { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 })
    .from(svg.querySelector('.axis'), { autoAlpha: 0, duration: 0.6 }, '-=0.3')
  gsap.set(svg.querySelector('.curve'), { drawSVG: 0 })

  tl.addLabel('step1')
    .from(svg.querySelectorAll('.readings circle'), { scale: 0, transformOrigin: '50% 50%', duration: 0.4, ease: 'back.out(3)', stagger: 0.025 })
    .from(slide.querySelectorAll('.legend .k-read'), { autoAlpha: 0, x: -20, duration: 0.4 }, 'step1')

  tl.addLabel('step2')
    .to(svg.querySelector('.curve'), { drawSVG: '100%', duration: 1.8, ease: 'power1.inOut' })
    .to(svg.querySelectorAll('.readings circle'), { opacity: 0.45, duration: 0.6 }, 'step2+=0.6')

  tl.addLabel('step3')
    .from(svg.querySelectorAll('.visit'), { y: -60, autoAlpha: 0, duration: 0.7, ease: 'bounce.out', stagger: 0.15 })
    .from(slide.querySelectorAll('.legend .k-visit'), { autoAlpha: 0, x: -20, duration: 0.4 }, 'step3')
  return tl
})
