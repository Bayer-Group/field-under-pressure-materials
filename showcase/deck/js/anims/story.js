// Animations for the story slides: title, problem, goal, data, future.
// Every builder follows engine.js: return a timeline, add labels step1, step2, ... for clicks.
;(function () {
  'use strict'
  const NS = 'http://www.w3.org/2000/svg'
  const TAXA = DeckData.taxa
  const TAU = Math.PI * 2

  // ---------- helpers ----------
  /** Seeded random numbers, so every replay draws the same picture. */
  function rng(seed) {
    let s = seed >>> 0 || 1
    return () => ((s = (s * 16807) % 2147483647) / 2147483647)
  }
  /** Pick a taxon in proportion to its share. */
  function pickTaxon(r) {
    let x = r() * 100
    for (const t of TAXA) if ((x -= t.pct) <= 0) return t
    return TAXA[TAXA.length - 1]
  }
  const svgEl = (tag, attrs = {}) => {
    const el = document.createElementNS(NS, tag)
    for (const k in attrs) el.setAttribute(k, attrs[k])
    return el
  }
  /** Kicker slides in, heading words rise. */
  function headIn(tl, slide, at = 0) {
    tl.from(slide.querySelectorAll('.kicker'), { x: -30, autoAlpha: 0, duration: 0.6, ease: 'power3.out' }, at)
    const head = slide.querySelector('.heading')
    if (head) {
      const split = SplitText.create(head, { type: 'words', mask: 'words' })
      tl.from(split.words, { yPercent: 110, duration: 0.8, stagger: 0.06, ease: 'power3.out' }, at + 0.05)
    }
    return tl
  }

  // ---------- line icons (24 x 24, stroke = currentColor) ----------
  const ICONS = {
    satellite: '<rect x="9.5" y="9.5" width="5" height="5" rx="1"/><rect x="2" y="10" width="5.5" height="4"/><rect x="16.5" y="10" width="5.5" height="4"/><path d="M7.5 12h2M14.5 12h2M12 14.5V17M8.5 20.5a5 5 0 0 1 7 0"/><path d="M4.75 10V14M19.25 10V14"/>',
    drone: '<circle cx="5" cy="6" r="2.6"/><circle cx="19" cy="6" r="2.6"/><path d="M7 7.6l2.6 2M17 7.6l-2.6 2"/><rect x="9.3" y="9.4" width="5.4" height="4.2" rx="1.2"/><path d="M10.2 13.6l-1.2 3M13.8 13.6l1.2 3M12 13.6v1.8"/><circle cx="12" cy="17.6" r="1.1"/>',
    sensor: '<path d="M2 15h20"/><path d="M5 18l1.5-1M18 18l1.5-1M9 19.5l1-1"/><rect x="10" y="4" width="4" height="6.5" rx="1"/><path d="M12 10.5V21"/><path d="M6.5 6.5a7 7 0 0 1 2.5-3M17.5 6.5a7 7 0 0 0-2.5-3"/>',
    tractor: '<circle cx="7" cy="16" r="4"/><circle cx="7" cy="16" r="1"/><circle cx="18.5" cy="17.5" r="2.5"/><path d="M3.5 12.5V7h6l2.2 5H19a2 2 0 0 1 2 2v1.5M11.7 12H4M8 7V4"/><path d="M11 17.5h5"/>',
    dna: '<path d="M7 2c0 6 10 6 10 10s-10 4-10 10M17 2c0 6-10 6-10 10s10 4 10 10"/><path d="M9.2 5h5.6M8.6 8.5h6.8M8.6 15.5h6.8M9.2 19h5.6"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3.2 3 3.2 15 0 18M12 3c-3.2 3-3.2 15 0 18M4.8 7h14.4M4.8 17h14.4"/>',
    sprout: '<path d="M12 21v-8.5"/><path d="M12 12.5c0-4-2.8-6.5-7.5-6.5 0 4 2.8 6.5 7.5 6.5zM12 14.5c0-3.3 2.6-5.5 7-5.5 0 3.3-2.6 5.5-7 5.5z"/><path d="M5 21h14"/>',
    bag: '<path d="M6 8h12l-1.2 13H7.2z"/><path d="M8 8l1.2-4.5h5.6L16 8"/><path d="M9.5 14.5h5M12 12v5"/>',
    spray: '<path d="M7 11h6.5v10H7z"/><path d="M8.3 11V7.5h4V11M12.3 8.5h3.2l1-2"/><circle cx="19.2" cy="8" r=".9"/><circle cx="20.5" cy="11" r=".9"/><circle cx="20.8" cy="5" r=".9"/><circle cx="18.6" cy="3" r=".9"/>',
    balance: '<path d="M12 6v15M8 21h8"/><circle cx="12" cy="4.4" r="1.4"/><g class="beam"><path d="M4 6.5h16"/><path d="M4 6.5l-2.6 6.2h5.2zM20 6.5l-2.6 6.2h5.2z"/></g>',
    flask: '<path d="M9 3h6M10 3v6.2L4.8 19a1.5 1.5 0 0 0 1.3 2.1h11.8a1.5 1.5 0 0 0 1.3-2.1L14 9.2V3"/><path d="M7.3 15h9.4"/><circle cx="10.5" cy="18" r=".9"/><circle cx="13.8" cy="17.2" r=".7"/>',
    leaf: '<path d="M5 19C5 10 11 5 20 5c0 9-5.2 14.5-14 14.5"/><path d="M5 19.5L13.5 11"/><path d="M9.5 12.5h3.5v-3.5"/>',
  }
  const iconSvg = (name) =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`
  document.querySelectorAll('[data-ico]').forEach((el) => (el.innerHTML = iconSvg(el.dataset.ico)))

  // ===================================================================================
  // 0 · Title: Geoinformatics ⇒ Terranos ⇐ Bioinformatics
  // A wireframe globe and a DNA helix fly in, collide, and the Terranos logo appears between them.
  // ===================================================================================
  let landCache = null
  function wireGlobe(canvas) {
    const px = 760
    canvas.width = canvas.height = px
    const ctx = canvas.getContext('2d')
    const proj = d3.geoOrthographic().translate([px / 2, px / 2]).scale(px / 2 - 6).clipAngle(90).precision(0.5)
    const path = d3.geoPath(proj, ctx)
    const grat = d3.geoGraticule10()
    landCache ||= topojson.feature(window.LAND_TOPO, window.LAND_TOPO.objects.land)
    const g = {
      lon: 10,
      lat: 20,
      draw() {
        proj.rotate([-g.lon, -g.lat, 0])
        ctx.clearRect(0, 0, px, px)
        ctx.beginPath(); path({ type: 'Sphere' })
        ctx.fillStyle = 'rgba(96,165,250,.10)'; ctx.fill()
        ctx.beginPath(); path(grat)
        ctx.lineWidth = 1.6; ctx.strokeStyle = 'rgba(96,165,250,.45)'; ctx.stroke()
        ctx.beginPath(); path(landCache)
        ctx.fillStyle = 'rgba(96,165,250,.30)'; ctx.fill()
        ctx.lineWidth = 2.6; ctx.strokeStyle = '#a9cdfc'; ctx.stroke()
        ctx.beginPath(); path({ type: 'Sphere' })
        ctx.lineWidth = 5; ctx.strokeStyle = '#60a5fa'; ctx.stroke()
      },
    }
    g.draw()
    return g
  }
  function makeHelix(svg) {
    const N = 13, cx = 110, A = 82, k = TAU / 200
    svg.setAttribute('viewBox', '0 0 220 380')
    svg.innerHTML = '<g class="rungs">' + '<line/>'.repeat(N) + '</g><path class="s2"/><path class="s1"/>'
    const rungs = [...svg.querySelectorAll('line')]
    const s1 = svg.querySelector('.s1'), s2 = svg.querySelector('.s2')
    const h = {
      phase: 0,
      draw() {
        let p1 = '', p2 = ''
        for (let y = 8; y <= 372; y += 6) {
          const x = A * Math.sin(k * y + h.phase)
          p1 += `${p1 ? 'L' : 'M'}${(cx + x).toFixed(1)},${y}`
          p2 += `${p2 ? 'L' : 'M'}${(cx - x).toFixed(1)},${y}`
        }
        s1.setAttribute('d', p1)
        s2.setAttribute('d', p2)
        rungs.forEach((l, i) => {
          const y = 22 + (i * 336) / (N - 1)
          const a = k * y + h.phase, x = A * Math.sin(a)
          l.setAttribute('x1', cx + x); l.setAttribute('x2', cx - x)
          l.setAttribute('y1', y); l.setAttribute('y2', y)
          l.style.opacity = (0.2 + 0.8 * Math.abs(Math.cos(a))).toFixed(2)
        })
      },
    }
    h.draw()
    return h
  }

  Deck.anim('collide', (slide, D) => {
    const geo = slide.querySelector('.orb.geo'), bio = slide.querySelector('.orb.bio')
    const sparks = slide.querySelector('.sparks')
    D.once(slide, 'collide', () => {
      sparks.innerHTML = Array.from({ length: 32 }, (_, i) => `<i style="background:${i % 2 ? 'var(--lime)' : 'var(--sky)'}"></i>`).join('')
    })
    const wire = wireGlobe(geo.querySelector('canvas'))
    const helix = makeHelix(bio.querySelector('svg.helix'))
    const { letters, globe } = D.lockup(slide.querySelector('.lockup'))
    const earth = D.earth(globe)
    D.loop(() => gsap.to(wire, { lon: '+=360', duration: 30, ease: 'none', repeat: -1, onUpdate: wire.draw }))
    D.loop(() => gsap.to(helix, { phase: `+=${TAU}`, duration: 4, ease: 'none', repeat: -1, onUpdate: helix.draw }))
    const spin = D.loop(() => gsap.to(earth, { lon: '-=360', duration: 36, ease: 'none', repeat: -1, onUpdate: earth.draw }))

    const hit = 1.5
    const tl = gsap.timeline()
    tl.fromTo(geo, { x: -520 }, { x: 575, duration: hit, ease: 'power2.in' }, 0)
      .fromTo(bio, { x: 520 }, { x: -575, duration: hit, ease: 'power2.in' }, 0)
      .from([geo, bio], { autoAlpha: 0, duration: 0.5 }, 0)
      .fromTo(slide.querySelector('.burst'), { scale: 0.2, opacity: 1 }, { scale: 7, opacity: 0, duration: 1.1, ease: 'power2.out', immediateRender: false }, hit)
    const r = rng(11)
    sparks.querySelectorAll('i').forEach((s) => {
      const a = r() * TAU, d = 260 + r() * 520
      tl.fromTo(s, { x: 0, y: 0, opacity: 1, scale: 1.4 }, { x: Math.cos(a) * d, y: Math.sin(a) * d * 0.7, opacity: 0, scale: 0.3, duration: 1 + r() * 0.6, ease: 'power3.out', immediateRender: false }, hit)
    })
    tl.to([geo, bio], { x: 0, scale: 0.58, duration: 1.3, ease: 'power3.out' }, hit + 0.05)
      .fromTo(letters, { clipPath: 'inset(0% 50% 0% 50%)' }, { clipPath: 'inset(0% 0% 0% 0%)', duration: 1.2, ease: 'power3.out' }, hit + 0.15)
      .from(globe, { scale: 0, rotation: -120, autoAlpha: 0, duration: 1.3, ease: 'back.out(1.6)' }, hit + 0.2)
      .from(slide.querySelectorAll('.orb .lbl'), { autoAlpha: 0, y: 40, duration: 0.7, ease: 'power3.out', stagger: 0.1 }, hit + 0.9)
      .fromTo(slide.querySelectorAll('.arrows path'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 0.8, ease: 'power2.inOut' }, hit + 1.1)
    if (spin) tl.fromTo(spin, { timeScale: 16 }, { timeScale: 1, duration: 3, ease: 'power2.out' }, hit)
    return tl
  })

  // ===================================================================================
  // 1a · Geoinformatic data sees the surface → GENOMICS reads the soil
  // Steps: 1 geoinformatic data · 2 arrow into the soil, GENOMICS
  // ===================================================================================
  Deck.anim('genomics', (slide, D) => {
    const ground = slide.querySelector('.ground')
    D.once(slide, 'ground', () => {
      const r = rng(5)
      let s = ''
      for (let i = 0; i < 54; i++) {
        const w = 12 + r() * 30, h = r() < 0.45 ? w * 0.6 : 12
        const t = TAXA[Math.floor(r() * TAXA.length)]
        s += `<i style="left:${(r() * 100).toFixed(1)}%;top:${(6 + r() * 88).toFixed(1)}%;width:${w.toFixed(0)}px;height:${h.toFixed(0)}px;background:${t.c};rotate:${Math.floor(r() * 180)}deg"></i>`
      }
      ground.innerHTML = s
    })
    const microbes = ground.querySelectorAll('i')
    D.loop(() => gsap.to(microbes, { x: 'random(-24, 24)', y: 'random(-14, 14)', duration: 'random(2, 4)', ease: 'sine.inOut', repeat: -1, yoyo: true }))

    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.from(ground, { autoAlpha: 0, y: 60, duration: 0.9 }, 0.2)
      .set(microbes, { opacity: 0.18 }, 0)
    tl.addLabel('step1')
      .from(slide.querySelectorAll('.tool'), { y: 70, autoAlpha: 0, duration: 0.7, stagger: 0.12, ease: 'back.out(1.6)' })
    tl.addLabel('step2')
      .fromTo(slide.querySelector('.dive path'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 0.8, ease: 'power2.inOut' })
      .to(microbes, { opacity: 0.85, duration: 0.6, stagger: { each: 0.012, from: 'center' } }, 'step2+=0.5')
      .from(slide.querySelector('.genomics i'), { scale: 0, rotation: -90, duration: 0.8, ease: 'back.out(2)' }, 'step2+=0.6')
    const word = SplitText.create(slide.querySelector('.genomics b'), { type: 'chars' })
    tl.from(word.chars, { yPercent: 80, autoAlpha: 0, duration: 0.6, stagger: 0.05 }, 'step2+=0.7')
    return tl
  })

  // ===================================================================================
  // 1c · Sequencing cost (log) and papers per year, two panels on one year axis.
  // Steps: 1 cost line · 2 paper bars
  // ===================================================================================
  Deck.anim('trend', (slide) => {
    const svg = slide.querySelector('svg.trend')
    const T = DeckData.trend
    const W = 1300, H = 720, L = 120, R = 1290, Y0 = 2001, Y1 = 2027
    const x = (yr) => L + ((yr - Y0) / (Y1 - Y0)) * (R - L)
    const cTop = 50, cBot = 300, pTop = 410, pBot = 640
    const yC = (v) => cBot - ((Math.log10(v) - 2) / 6) * (cBot - cTop)
    const yP = (v) => pBot - (v / 2000) * (pBot - pTop)

    Deck.once(slide, 'trend', () => {
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`)
      const fmt = (n) => n.toLocaleString('en-US')
      let s = `<defs><pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="10" height="10" fill="rgba(181,242,107,.12)"/><line x1="0" y1="0" x2="0" y2="10" stroke="#b5f26b" stroke-width="4"/></pattern></defs>`
      s += '<g class="grid">'
      for (let yr = 2005; yr <= 2025; yr += 5) s += `<line x1="${x(yr)}" x2="${x(yr)}" y1="${cTop}" y2="${pBot}"/>`
      ;[[1e2, '$100'], [1e4, '$10k'], [1e6, '$1M'], [1e8, '$100M']].forEach(([v, t]) => {
        s += `<line x1="${L}" x2="${R}" y1="${yC(v)}" y2="${yC(v)}"/><text x="${L - 16}" y="${yC(v) + 8}" text-anchor="end">${t}</text>`
      })
      ;[0, 1000, 2000].forEach((v) => {
        s += `<line x1="${L}" x2="${R}" y1="${yP(v)}" y2="${yP(v)}"/><text x="${L - 16}" y="${yP(v) + 8}" text-anchor="end">${fmt(v)}</text>`
      })
      s += `<text class="ptitle" x="${L}" y="${cTop - 36}">Cost per human genome</text>`
      s += `<text class="ptitle" x="${L}" y="${pTop - 30}">Papers per year · PubMed</text></g>`
      s += '<g class="xaxis">'
      for (let yr = 2005; yr <= 2025; yr += 5) s += `<text x="${x(yr)}" y="${pBot + 44}" text-anchor="middle">${yr}</text>`
      s += '</g>'
      // cost line
      const d = T.cost.map(([t, v], i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)},${yC(v).toFixed(1)}`).join('')
      const first = T.cost[0], last = T.cost[T.cost.length - 1]
      s += `<path class="cost" d="${d}"/>`
      s += `<g class="cends"><circle class="cdot" cx="${x(first[0])}" cy="${yC(first[1])}" r="10"/><text class="clabel" x="${x(first[0]) + 22}" y="${yC(first[1]) + 4}">$95M</text>`
      s += `<circle class="cdot" cx="${x(last[0])}" cy="${yC(last[1])}" r="10"/><text class="clabel" x="${x(last[0]) + 22}" y="${yC(last[1]) + 10}">$525</text></g>`
      s += '<g class="cost-hits">' + T.cost.map(([t, v]) => `<circle cx="${x(t)}" cy="${yC(v)}" r="14" fill="transparent"><title>${Math.floor(t)}: $${fmt(Math.round(v))} per genome</title></circle>`).join('') + '</g>'
      // paper bars, rounded at the top only
      const bw = 30
      s += '<g class="bars">'
      for (const [yr, n, partial] of T.papers) {
        const cx = x(yr + 0.5), x0 = cx - bw / 2, x1 = cx + bw / 2, yt = yP(n), rr = Math.min(4, pBot - yt)
        s += `<path class="${partial ? 'partial' : ''}" d="M${x0},${pBot}V${yt + rr}Q${x0},${yt} ${x0 + rr},${yt}H${x1 - rr}Q${x1},${yt} ${x1},${yt + rr}V${pBot}Z">`
        s += `<title>${yr}${partial ? ' (so far)' : ''}: ${fmt(n)} papers</title></path>`
      }
      s += '</g>'
      const p25 = T.papers.find((p) => p[0] === 2025), p26 = T.papers.find((p) => p[2])
      s += `<g class="blabels"><text class="blabel" x="${x(2025.5) + 16}" y="${yP(p25[1]) - 14}" text-anchor="end">${fmt(p25[1])}</text>`
      s += `<text class="vtxt" x="${x(2026.5)}" y="${yP(p26[1]) - 12}" text-anchor="middle" fill="var(--soft)" font-size="20">so far</text></g>`
      svg.innerHTML = s
    })

    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.from(svg.querySelectorAll('.grid, .xaxis'), { autoAlpha: 0, duration: 0.6 }, 0.3)
    tl.addLabel('step1')
      .fromTo(svg.querySelector('.cost'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 2, ease: 'power1.inOut' })
      .from(svg.querySelectorAll('.cends > *'), { autoAlpha: 0, scale: 0, transformOrigin: '50% 50%', duration: 0.4, stagger: 0.1 }, 'step1+=1.6')
      .from(slide.querySelector('.co.cost'), { x: 60, autoAlpha: 0, duration: 0.7 }, 'step1+=1.2')
    tl.addLabel('step2')
      .from(svg.querySelectorAll('.bars path'), { scaleY: 0, transformOrigin: '50% 100%', duration: 0.6, stagger: 0.05, ease: 'power2.out' })
      .from(svg.querySelectorAll('.blabels text'), { autoAlpha: 0, y: 10, duration: 0.4 }, '-=0.2')
      .from(slide.querySelector('.co.pubs'), { x: 60, autoAlpha: 0, duration: 0.7 }, 'step2+=0.8')
    return tl
  })

  // ===================================================================================
  // 1b · What is metagenomics: soil sample → all its DNA → who lives there
  // Steps: 1 DNA reads fly out of the soil · 2 composition bar
  // ===================================================================================
  Deck.anim('meta', (slide, D) => {
    const soil = slide.querySelector('.soilbox'), reads = slide.querySelector('.reads'), comp = slide.querySelector('.comp')
    const stages = slide.querySelectorAll('.stage'), arrows = slide.querySelectorAll('.arrow')
    const gap = stages[1].offsetLeft - stages[0].offsetLeft
    D.once(slide, 'meta', () => {
      const r = rng(21)
      let s = ''
      for (let i = 0; i < 38; i++) {
        const a = r() * TAU, d = Math.sqrt(r()) * 160
        const t = pickTaxon(r)
        const round = r() < 0.3
        s += `<i style="left:${(220 + Math.cos(a) * d - 13).toFixed(0)}px;top:${(220 + Math.sin(a) * d - 7).toFixed(0)}px;width:${round ? 16 : 28}px;height:${round ? 16 : 13}px;background:${t.c};rotate:${Math.floor(r() * 180)}deg"></i>`
      }
      soil.innerHTML = s
      s = ''
      for (let row = 0; row < 16; row++) {
        let xx = r() * 40
        while (xx < 380) {
          const w = 50 + r() * 70
          if (xx + w > 440) break
          s += `<i style="left:${xx.toFixed(0)}px;top:${(14 + row * 26).toFixed(0)}px;width:${w.toFixed(0)}px;height:12px;background:${pickTaxon(r).c}"></i>`
          xx += w + 10 + r() * 30
        }
      }
      reads.innerHTML = s
      // tall segmented bar with a label beside each segment
      const svg = svgEl('svg', { viewBox: '0 0 440 440' })
      let y = 10
      const H = 420, g = 4
      TAXA.forEach((t) => {
        const h = (t.pct / 100) * (H - g * (TAXA.length - 1))
        const seg = svgEl('g', { class: 'seg' })
        seg.append(svgEl('rect', { x: 30, y, width: 120, height: h, rx: 4, fill: t.c }))
        const label = svgEl('text', { x: 176, y: y + h / 2 + 9 })
        label.textContent = `${t.name} ${t.pct}%`
        seg.append(label)
        svg.append(seg)
        y += h + g
      })
      comp.append(svg)
    })
    const microbes = soil.querySelectorAll('i')
    D.loop(() => gsap.to(microbes, { x: 'random(-10, 10)', y: 'random(-10, 10)', rotation: 'random(-30, 30)', duration: 'random(1.5, 3)', ease: 'sine.inOut', repeat: -1, yoyo: true }))

    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.from(stages[0], { autoAlpha: 0, scale: 0.8, duration: 0.8, ease: 'back.out(1.5)' }, 0.3)
      .from(microbes, { scale: 0, duration: 0.4, stagger: 0.015, ease: 'back.out(3)' }, 0.6)
      .set([stages[1].querySelector('span'), stages[2].querySelector('span'), ...arrows], { autoAlpha: 0 }, 0)
    tl.addLabel('step1')
      .to(arrows[0], { autoAlpha: 1, duration: 0.4 })
    const r = rng(3)
    reads.querySelectorAll('i').forEach((el) => {
      tl.from(el, { x: -gap - el.offsetLeft + 120 + r() * 200, y: 120 + r() * 200 - el.offsetTop, rotation: r() * 360 - 180, scale: 0.3, autoAlpha: 0, duration: 1.1, ease: 'power3.inOut' }, `step1+=${0.1 + r() * 0.6}`)
    })
    tl.to(stages[1].querySelector('span'), { autoAlpha: 1, duration: 0.5 }, 'step1+=1.2')
    tl.addLabel('step2')
      .to(arrows[1], { autoAlpha: 1, duration: 0.4 })
      .from(comp.querySelectorAll('.seg rect'), { scaleY: 0, transformOrigin: '50% 0%', duration: 0.5, stagger: 0.12 }, 'step2+=0.2')
      .from(comp.querySelectorAll('.seg text'), { x: -20, autoAlpha: 0, duration: 0.4, stagger: 0.12 }, 'step2+=0.4')
      .to(stages[2].querySelector('span'), { autoAlpha: 1, duration: 0.5 }, 'step2+=0.9')
    return tl
  })

  // ===================================================================================
  // 1d · Metagenomics + Geoinformation: two map layers slide together, pins go through both.
  // Steps: 1 layers merge and pins drop
  // ===================================================================================
  Deck.anim('merge', (slide, D) => {
    const geo = slide.querySelector('.slab.geo'), bio = slide.querySelector('.slab.bio')
    const SIZE = 520, CELLS = 8, cell = SIZE / CELLS
    const GEO_Y = 520, BIO_Y = 690 // final screen centre of each layer
    const ramp = ['#6b4f2a', '#8a7a34', '#6f9e3c', '#3fae5e', '#9fe36a']
    const pins = [[1, 2], [5, 2], [3, 5], [6, 6]]
    // screen position of plane coordinates (u, v), for the transform rotateX(58deg) rotateZ(-45deg)
    const project = (u, v, cy) => {
      const x = u - SIZE / 2, y = v - SIZE / 2
      return [960 + (x - y) * Math.SQRT1_2, cy + (x + y) * Math.SQRT1_2 * Math.cos((58 * Math.PI) / 180)]
    }
    D.once(slide, 'merge', () => {
      const r = rng(8)
      let s = ''
      for (let j = 0; j < CELLS; j++) for (let i = 0; i < CELLS; i++) {
        const v = 0.5 + 0.3 * Math.sin(i * 0.9 + 0.5) * Math.cos(j * 0.7) + (r() - 0.5) * 0.35
        s += `<i style="background:${ramp[Math.max(0, Math.min(4, Math.floor(v * 5)))]}"></i>`
      }
      geo.querySelector('.plane').innerHTML = s
      s = ''
      for (let k = 0; k < 70; k++) {
        const round = r() < 0.3
        s += `<i style="left:${(10 + r() * 480).toFixed(0)}px;top:${(10 + r() * 480).toFixed(0)}px;width:${round ? 14 : 26}px;height:${round ? 14 : 11}px;background:${pickTaxon(r).c};rotate:${Math.floor(r() * 180)}deg"></i>`
      }
      bio.querySelector('.plane').innerHTML = s
      geo.style.top = `${GEO_Y - SIZE / 2}px`
      bio.style.top = `${BIO_Y - SIZE / 2}px`
      pins.forEach(([i, j]) => {
        const u = (i + 0.5) * cell, v = (j + 0.5) * cell
        const [sx, sy] = project(u, v, GEO_Y), [, by] = project(u, v, BIO_Y)
        const pin = document.createElement('div')
        pin.className = 'pin'
        Object.assign(pin.style, { left: `${sx}px`, top: `${sy - 80}px`, height: `${by - sy + 80}px` })
        pin.innerHTML = '<b></b>'
        slide.append(pin)
      })
    })
    const pinEls = slide.querySelectorAll('.pin')
    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.fromTo(geo, { y: -330, autoAlpha: 0 }, { y: -170, autoAlpha: 1, duration: 1 }, 0.3)
      .fromTo(bio, { y: 330, autoAlpha: 0 }, { y: 170, autoAlpha: 1, duration: 1 }, 0.3)
      .from(slide.querySelectorAll('.stag'), { autoAlpha: 0, duration: 0.6, stagger: 0.15 }, 0.9)
      .set(pinEls, { autoAlpha: 0 }, 0)
    tl.addLabel('step1')
      .to([geo, bio], { y: 0, duration: 1.1, ease: 'power3.inOut' })
      .to(slide.querySelectorAll('.plane'), { boxShadow: '0 0 0 3px rgba(181,242,107,.7), 0 60px 80px rgba(0,0,0,.45)', duration: 0.5 }, 'step1+=0.9')
    pinEls.forEach((p, i) => {
      tl.set(p, { autoAlpha: 1 }, `step1+=${1.1 + i * 0.15}`)
        .from(p, { scaleY: 0, transformOrigin: '50% 0%', duration: 0.5, ease: 'power2.out' }, `step1+=${1.1 + i * 0.15}`)
        .from(p.querySelector('b'), { y: -60, scale: 0, duration: 0.5, ease: 'back.out(2)' }, `step1+=${1.1 + i * 0.15}`)
    })
    return tl
  })

  // ===================================================================================
  // 2a · Goal: geo + metagenomics → analysis → sowing / fertilization / spraying → biological order
  // Steps: 1 analysis · 2 actions · 3 balance
  // ===================================================================================
  Deck.anim('goal', (slide, D) => {
    const flow = slide.querySelector('.flow'), svg = flow.querySelector('svg')
    const P = { in1: [130, 170], in2: [130, 530], core: [560, 350], a1: [1010, 110], a2: [1010, 350], a3: [1010, 590], out: [1470, 350] }
    const LINKS = [['in1', 'core', 1], ['in2', 'core', 1], ['core', 'a1', 2], ['core', 'a2', 2], ['core', 'a3', 2], ['a1', 'out', 3], ['a2', 'out', 3], ['a3', 'out', 3]]
    D.once(slide, 'goal', () => {
      svg.setAttribute('viewBox', '0 0 1640 720')
      for (const k in P) {
        const n = flow.querySelector(`.node.${k}`)
        n.style.left = `${P[k][0]}px`
        n.style.top = `${P[k][1]}px`
      }
      LINKS.forEach(([a, b, step]) => {
        const [x1, y1] = P[a], [x2, y2] = P[b], dx = (x2 - x1) / 2
        svg.append(svgEl('path', { class: `link s${step}`, d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` }))
      })
      LINKS.forEach(([, , step]) => svg.append(svgEl('circle', { class: `pulse s${step}`, r: 9 })))
    })
    const links = [...svg.querySelectorAll('.link')], pulses = [...svg.querySelectorAll('.pulse')]
    pulses.forEach((c, i) =>
      D.loop(() => gsap.to(c, { motionPath: { path: links[i], align: links[i], alignOrigin: [0.5, 0.5] }, duration: 1.8, ease: 'none', repeat: -1, delay: (i % 3) * 0.5 })),
    )
    const kids = (sel) => flow.querySelectorAll(`${sel} > *`)
    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.set([links, pulses], { autoAlpha: 0 }, 0)
      .from(kids('.in'), { scale: 0.5, autoAlpha: 0, duration: 0.7, stagger: 0.1, ease: 'back.out(1.6)' }, 0.4)
      .set(flow.querySelectorAll('.core, .act, .out'), { autoAlpha: 0 }, 0)
    for (const step of [1, 2, 3]) {
      const ls = svg.querySelectorAll(`.link.s${step}`), ps = svg.querySelectorAll(`.pulse.s${step}`)
      const target = step === 1 ? '.core' : step === 2 ? '.act' : '.out'
      tl.addLabel(`step${step}`)
        .set(ls, { autoAlpha: 1 })
        .fromTo(ls, { drawSVG: '0%' }, { drawSVG: '100%', duration: 0.7, stagger: 0.08, ease: 'power2.inOut' })
        .set(flow.querySelectorAll(target), { autoAlpha: 1 }, '-=0.2')
        .from(kids(target), { scale: 0.4, autoAlpha: 0, duration: 0.7, stagger: 0.08, ease: 'back.out(1.8)' }, '<')
        .to(ps, { autoAlpha: 1, duration: 0.3 })
    }
    tl.fromTo(flow.querySelector('.out .beam'), { rotation: -16, svgOrigin: '12 6.5' }, { rotation: 0, svgOrigin: '12 6.5', duration: 1.6, ease: 'elastic.out(1, 0.35)' }, 'step3+=1')
    return tl
  })

  // ===================================================================================
  // 2b · History → now → future: past readings, a "?" at now, the future branches and one wins.
  // Steps: 1 history and now · 2 futures
  // ===================================================================================
  Deck.anim('timeline', (slide, D) => {
    const svg = slide.querySelector('svg.tl')
    const NOW = 900, BASE = 560, NY = 400
    D.once(slide, 'timeline', () => {
      svg.setAttribute('viewBox', '0 0 1640 680')
      const r = rng(4)
      const season = 172
      let d = ''
      for (let xx = 10; xx <= NOW - 40; xx += 6) {
        const ph = ((xx - 10) % season) / season
        const yy = 430 - 210 * Math.pow(Math.sin(Math.PI * ph), 1.6) + (r() - 0.5) * 16
        d += `${d ? 'L' : 'M'}${xx},${yy.toFixed(1)}`
      }
      d += ` L${NOW - 50},${NY}`
      let s = `<rect class="pastbg" x="0" y="60" width="${NOW}" height="${BASE - 60}" rx="8"/>`
      s += `<line class="axis" x1="0" x2="1640" y1="${BASE}" y2="${BASE}"/>`
      s += `<path class="past" d="${d}"/>`
      s += '<g class="samples">' + [95, 270, 440, 610, 780].map((sx) => `<rect class="sample" x="${sx - 11}" y="${BASE - 11}" width="22" height="22" transform="rotate(45 ${sx} ${BASE})"/>`).join('') + '</g>'
      s += `<text class="zone z-past" x="${NOW / 2}" y="${BASE + 62}" text-anchor="middle">History</text>`
      s += `<text class="zone z-fut" x="${(NOW + 1640) / 2}" y="${BASE + 62}" text-anchor="middle">Future</text>`
      const B0 = `M${NOW + 50},${NY}`
      s += `<path class="branch bad" d="${B0} C${NOW + 300},${NY} ${NOW + 400},${BASE - 30} 1600,${BASE - 40}"/>`
      s += `<path class="branch flat" d="${B0} C${NOW + 300},${NY} ${NOW + 400},${NY + 20} 1600,${NY + 10}"/>`
      s += `<path class="branch good" d="${B0} C${NOW + 300},${NY} ${NOW + 380},150 1590,120"/>`
      s += `<g class="goal"><circle cx="1590" cy="120" r="20"/><text x="1590" y="76" text-anchor="end">Good future</text></g>`
      s += `<line class="nowline" x1="${NOW}" x2="${NOW}" y1="60" y2="${BASE}"/>`
      s += `<text class="nowlbl" x="${NOW}" y="36" text-anchor="middle">NOW</text>`
      s += `<g class="now"><circle class="ring" cx="${NOW}" cy="${NY}" r="50"/><circle cx="${NOW}" cy="${NY}" r="50"/>`
      s += `<text class="q" x="${NOW}" y="${NY + 22}" text-anchor="middle">?</text><text class="ok" x="${NOW}" y="${NY + 22}" text-anchor="middle">✓</text></g>`
      svg.innerHTML = s
    })
    const $ = (q) => svg.querySelector(q), $$ = (q) => svg.querySelectorAll(q)
    const ring = $('.now .ring')
    D.loop(() => gsap.fromTo(ring, { scale: 1, opacity: 0.8, transformOrigin: '50% 50%' }, { scale: 1.8, opacity: 0, duration: 1.6, ease: 'power1.out', repeat: -1 }))

    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.from($$('.axis, .pastbg'), { autoAlpha: 0, duration: 0.6 }, 0.3)
      .set($$('.now, .nowline, .nowlbl, .branch, .goal, .zone, .samples rect'), { autoAlpha: 0 }, 0)
      .set($('.ok'), { autoAlpha: 0 }, 0)
    tl.addLabel('step1')
      .fromTo($('.past'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 1.8, ease: 'power1.inOut' })
      .to($$('.samples rect'), { autoAlpha: 1, duration: 0.3, stagger: 0.25 }, 'step1+=0.2')
      .to($('.z-past'), { autoAlpha: 1, duration: 0.5 }, 'step1+=0.4')
      .to($$('.nowline, .nowlbl'), { autoAlpha: 1, duration: 0.4 }, 'step1+=1.6')
      .to($('.now'), { autoAlpha: 1, duration: 0.2 }, 'step1+=1.7')
      .from($('.now'), { scale: 0, transformOrigin: '50% 50%', duration: 0.7, ease: 'back.out(2.2)' }, 'step1+=1.7')
    tl.addLabel('step2')
      .to($$('.branch.bad, .branch.flat'), { autoAlpha: 1, duration: 0.5, stagger: 0.15 })
      .set($('.branch.good'), { autoAlpha: 1 }, 'step2+=0.4')
      .fromTo($('.branch.good'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 1.2, ease: 'power2.inOut' }, 'step2+=0.4')
      .to($$('.branch.bad, .branch.flat'), { autoAlpha: 0.3, duration: 0.6 }, 'step2+=1')
      .to($('.goal'), { autoAlpha: 1, duration: 0.2 }, 'step2+=1.5')
      .from($('.goal circle'), { scale: 0, transformOrigin: '50% 50%', duration: 0.6, ease: 'back.out(3)' }, 'step2+=1.5')
      .to($('.q'), { autoAlpha: 0, duration: 0.3 }, 'step2+=1.5')
      .to($('.ok'), { autoAlpha: 1, duration: 0.3 }, 'step2+=1.7')
      .to($('.z-fut'), { autoAlpha: 1, duration: 0.5 }, 'step2+=1.6')
    return tl
  })

  // ===================================================================================
  // 3 · Data: four tiles, each with a small live visual.
  // Steps: 1 shotgun sequencing · 2 NDVI · 3 geochemistry · 4 qPCR
  // ===================================================================================
  function buildShotgun(svg, r) {
    let s = '<path class="strand" d="'
    for (let xx = 10; xx <= 310; xx += 5) s += `${xx === 10 ? 'M' : 'L'}${xx},${(50 + 16 * Math.sin(xx / 14)).toFixed(1)}`
    s += '"/><path class="strand" d="'
    for (let xx = 10; xx <= 310; xx += 5) s += `${xx === 10 ? 'M' : 'L'}${xx},${(50 - 16 * Math.sin(xx / 14)).toFixed(1)}`
    s += '" opacity=".55"/><g class="rd">'
    for (let row = 0; row < 13; row++) {
      let xx = r() * 30
      while (true) {
        const w = 44 + r() * 60
        if (xx + w > 320) break
        s += `<rect x="${xx.toFixed(0)}" y="${120 + row * 21}" width="${w.toFixed(0)}" height="12" rx="4" fill="${pickTaxon(r).c}"/>`
        xx += w + 8 + r() * 26
      }
    }
    svg.innerHTML = s + '</g>'
  }
  function buildNdvi(svg, r) {
    const ramp = ['#6b4f2a', '#8a7a34', '#6f9e3c', '#3fae5e', '#9fe36a']
    let s = '<g class="cells">'
    for (let j = 0; j < 9; j++) for (let i = 0; i < 10; i++) {
      const field = (i < 4 ? 0.75 : i < 7 ? 0.35 : 0.6) + (j > 5 ? -0.15 : 0)
      const v = Math.max(0, Math.min(0.999, field + (r() - 0.5) * 0.3))
      s += `<rect x="${i * 32 + 1}" y="${20 + j * 32}" width="30" height="30" rx="4" fill="${ramp[Math.floor(v * 5)]}" data-row="${j}"/>`
    }
    s += '</g><rect class="scanline" x="0" y="18" width="320" height="6" rx="3" fill="#b5f26b"/>'
    s += '<defs><linearGradient id="ndvi-ramp">' + ramp.map((c, i) => `<stop offset="${i / 4}" stop-color="${c}"/>`).join('') + '</linearGradient></defs>'
    s += '<g class="key"><rect x="60" y="330" width="200" height="14" rx="7" fill="url(#ndvi-ramp)"/><text class="vtxt" x="48" y="344" text-anchor="end">low</text><text class="vtxt" x="272" y="344">high</text></g>'
    svg.innerHTML = s
  }
  const PH = { lo: 4, hi: 9, value: 6.4 }
  const phAngle = (ph) => ((ph - PH.lo) / (PH.hi - PH.lo)) * 180 - 90 // -90 = left end, +90 = right end
  function buildGeochem(svg) {
    const cx = 160, cy = 175, R = 118
    const cols = ['#d95926', '#c98500', '#9fe36a', '#199e70', '#3987e5']
    let s = ''
    cols.forEach((c, i) => {
      const a0 = Math.PI + (i / 5) * Math.PI + 0.03, a1 = Math.PI + ((i + 1) / 5) * Math.PI - 0.03
      s += `<path d="M${cx + R * Math.cos(a0)},${cy + R * Math.sin(a0)} A${R},${R} 0 0 1 ${cx + R * Math.cos(a1)},${cy + R * Math.sin(a1)}" stroke="${c}" stroke-width="22" fill="none"/>`
    })
    s += `<line class="needle" x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy - 96}"/><circle cx="${cx}" cy="${cy}" r="12" fill="var(--cream)"/>`
    s += `<text class="vtxt" x="${cx - R}" y="${cy + 36}" text-anchor="middle">acid</text><text class="vtxt" x="${cx + R}" y="${cy + 36}" text-anchor="middle">alkaline</text>`
    s += `<text class="big" x="${cx}" y="${cy + 72}" text-anchor="middle">pH <tspan class="phv">${PH.value.toFixed(1)}</tspan></text>`
    ;[['N', 90], ['P', 55], ['K', 75]].forEach(([n, h], i) => {
      const x = 80 + i * 80
      s += `<rect class="bar" x="${x - 22}" y="${362 - h}" width="44" height="${h}" rx="4"/><text class="blbl" x="${x}" y="${396}" text-anchor="middle">${n}</text>`
    })
    svg.innerHTML = s
  }
  function buildQpcr(svg) {
    const X0 = 30, X1 = 310, YB = 330, YT = 40, THR = 230
    let s = `<line class="ax" x1="${X0}" y1="${YT}" x2="${X0}" y2="${YB}"/><line class="ax" x1="${X0}" y1="${YB}" x2="${X1}" y2="${YB}"/>`
    s += `<line class="thr" x1="${X0}" y1="${THR}" x2="${X1}" y2="${THR}"/>`
    const sig = (xx, ct) => YB - (YB - YT - 20) / (1 + Math.exp(-(xx - ct) / 16))
    ;[[130, TAXA[0].c], [180, TAXA[2].c], [235, TAXA[1].c]].forEach(([ct, c]) => {
      let d = ''
      for (let xx = X0; xx <= X1; xx += 4) d += `${d ? 'L' : 'M'}${xx},${sig(xx, ct).toFixed(1)}`
      s += `<path class="curve" d="${d}" stroke="${c}"/>`
      // where the curve crosses the threshold
      const cross = ct - 16 * Math.log((YB - YT - 20) / (YB - THR) - 1)
      s += `<circle class="ct" cx="${cross.toFixed(1)}" cy="${THR}" r="8" fill="${c}" stroke="var(--ink)" stroke-width="3"/>`
    })
    s += `<text class="vtxt" x="${X1}" y="${YB + 34}" text-anchor="end">cycles →</text><text class="vtxt" x="${X1}" y="${THR - 12}" text-anchor="end">threshold</text>`
    svg.innerHTML = s
  }

  Deck.anim('stack', (slide, D) => {
    const tiles = slide.querySelectorAll('.tile')
    const svgs = [...tiles].map((t) => t.querySelector('svg.viz'))
    D.once(slide, 'stack', () => {
      svgs.forEach((s) => s.setAttribute('viewBox', '0 0 320 400'))
      const r = rng(17)
      buildShotgun(svgs[0], r)
      buildNdvi(svgs[1], r)
      buildGeochem(svgs[2])
      buildQpcr(svgs[3])
    })
    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.fromTo(tiles, { y: 60, autoAlpha: 0 }, { y: 0, autoAlpha: 0.3, duration: 0.7, stagger: 0.08 }, 0.3)

    // 1 · shotgun: the strand breaks into short reads that pile up below
    const [sg, nd, gc, qp] = svgs
    const r = rng(9)
    tl.addLabel('step1').to(tiles[0], { opacity: 1, duration: 0.4 })
    sg.querySelectorAll('.rd rect').forEach((el) => {
      tl.from(el, { x: () => r() * 200 - 100, y: () => -(+el.getAttribute('y')) + 50, rotation: () => r() * 120 - 60, autoAlpha: 0, transformOrigin: '50% 50%', duration: 0.9, ease: 'power2.out' }, `step1+=${0.3 + r() * 0.7}`)
    })
    tl.to(sg.querySelectorAll('.strand'), { opacity: 0.15, duration: 0.6 }, 'step1+=0.3')

    // 2 · NDVI: a satellite pass colours the field row by row
    tl.addLabel('step2').to(tiles[1], { opacity: 1, duration: 0.4 })
      .fromTo(nd.querySelector('.scanline'), { y: 0, autoAlpha: 1 }, { y: 288, duration: 1.4, ease: 'none' }, 'step2+=0.2')
      .to(nd.querySelector('.scanline'), { autoAlpha: 0, duration: 0.3 })
    nd.querySelectorAll('.cells rect').forEach((c) => {
      tl.from(c, { fill: '#203a2c', duration: 0.3 }, `step2+=${0.2 + (+c.dataset.row / 9) * 1.4}`)
    })
    tl.from(nd.querySelector('.key'), { autoAlpha: 0, duration: 0.4 }, 'step2+=1.4')

    // 3 · geochemistry: the pH needle swings, N P K bars grow
    const phv = gc.querySelector('.phv'), ph = { v: PH.lo }
    tl.addLabel('step3').to(tiles[2], { opacity: 1, duration: 0.4 })
      .fromTo(gc.querySelector('.needle'), { rotation: phAngle(PH.lo), svgOrigin: '160 175' }, { rotation: phAngle(PH.value), svgOrigin: '160 175', duration: 1.6, ease: 'elastic.out(1, 0.45)' }, 'step3+=0.2')
      .fromTo(ph, { v: PH.lo }, { v: PH.value, duration: 1.2, ease: 'power2.out', onUpdate: () => (phv.textContent = ph.v.toFixed(1)) }, 'step3+=0.2')
      .from(gc.querySelectorAll('.bar'), { scaleY: 0, transformOrigin: '50% 100%', duration: 0.6, stagger: 0.12 }, 'step3+=0.6')

    // 4 · qPCR: amplification curves rise past the threshold
    tl.addLabel('step4').to(tiles[3], { opacity: 1, duration: 0.4 })
      .fromTo(qp.querySelectorAll('.curve'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 1.4, stagger: 0.25, ease: 'power1.inOut' }, 'step4+=0.2')
      .from(qp.querySelectorAll('.ct'), { scale: 0, transformOrigin: '50% 50%', duration: 0.4, stagger: 0.25, ease: 'back.out(3)' }, 'step4+=1')
    return tl
  })

  // ===================================================================================
  // 4 · Demo break: the showcase video grows from a card to full screen and plays with sound.
  // ===================================================================================
  Deck.anim('reel', (slide) => {
    const screen = slide.querySelector('.screen'), video = screen.querySelector('video')
    video.pause()
    video.currentTime = 0
    video.muted = false
    // Browsers may refuse sound without a recent key press or click: fall back to muted playback.
    const play = () => video.play().catch(() => ((video.muted = true), video.play().catch(() => {})))
    const tl = gsap.timeline()
    tl.fromTo(screen, { scale: 0.55, borderRadius: 48, autoAlpha: 0 }, { scale: 1, borderRadius: 0, autoAlpha: 1, duration: 1, ease: 'power3.inOut' })
      .call(play, null, 0.2)
    return tl
  })

  // ===================================================================================
  // 5 · Future: a road with two milestones.
  // Steps: 1 agro-chemical branch · 2 EU sustainability
  // ===================================================================================
  Deck.anim('future', (slide, D) => {
    const path = slide.querySelector('.road .path')
    const M = [[700, 600], [1400, 640]]
    D.once(slide, 'future', () => {
      slide.querySelectorAll('.ms').forEach((m, i) => {
        m.style.left = `${M[i][0]}px`
        m.style.top = `${M[i][1]}px`
      })
      slide.querySelector('.stars').innerHTML = Array.from({ length: 12 }, (_, i) =>
        `<span style="transform:rotate(${i * 30}deg) translate(0,-128px) rotate(${-i * 30}deg)">★</span>`).join('')
    })
    // path length fraction closest to each milestone
    const len = path.getTotalLength()
    const frac = M.map(([mx, my]) => {
      let best = 0, bd = Infinity
      for (let l = 0; l <= len; l += 4) {
        const p = path.getPointAtLength(l), d = (p.x - mx) ** 2 + (p.y - my) ** 2
        if (d < bd) (bd = d), (best = l)
      }
      return (best / len) * 100
    })
    const [m1, m2] = slide.querySelectorAll('.ms')
    const tl = headIn(gsap.timeline({ defaults: { ease: 'power3.out' } }), slide)
    tl.from(slide.querySelector('.road .bed'), { autoAlpha: 0, duration: 0.6 }, 0.3)
      .fromTo(path, { drawSVG: '0%' }, { drawSVG: '0%', duration: 0.01 }, 0)
      .set([m1, m2], { autoAlpha: 0 }, 0)
    tl.addLabel('step1')
      .to(path, { drawSVG: `${frac[0]}%`, duration: 1.2, ease: 'power2.inOut' })
      .set(m1, { autoAlpha: 1 }, '-=0.2')
      .from(m1.querySelector('.badge'), { scale: 0, rotation: -90, duration: 0.8, ease: 'back.out(1.8)' }, '<')
      .from(m1.querySelector('b'), { y: -20, autoAlpha: 0, duration: 0.6 }, '-=0.4')
    tl.addLabel('step2')
      .to(path, { drawSVG: '100%', duration: 1.4, ease: 'power2.inOut' })
      .set(m2, { autoAlpha: 1 }, 'step2+=0.6')
      .from(m2.querySelector('.badge'), { scale: 0, duration: 0.8, ease: 'back.out(1.8)' }, 'step2+=0.6')
      .from(m2.querySelectorAll('.stars span'), { scale: 0, autoAlpha: 0, duration: 0.35, stagger: 0.06, ease: 'back.out(3)' }, 'step2+=0.9')
      .from(m2.querySelector('.stars'), { rotation: -120, duration: 1.4, ease: 'power3.out' }, 'step2+=0.9')
      .from(m2.querySelector('b'), { y: -20, autoAlpha: 0, duration: 0.6 }, 'step2+=1.3')
    return tl
  })

  // ===================================================================================
  // Outro: the logo builds, "Thank you" rises.
  // ===================================================================================
  Deck.anim('finale', (slide, D) => {
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    const split = SplitText.create(slide.querySelector('.heading'), { type: 'words', mask: 'words' })
    tl.add(D.lockupIn(slide.querySelector('.lockup'))).from(split.words, { yPercent: 110, duration: 0.9, stagger: 0.08 }, '-=0.6')
    return tl
  })
})()
