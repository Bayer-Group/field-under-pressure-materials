// Live demo: embeds the running GUI if it answers, otherwise plays the 30-second showcase video.
//   <section data-anim="demo"> with  <iframe data-url="http://127.0.0.1:8000">  and a <video>.
Deck.anim('demo', (slide) => {
  const frame = slide.querySelector('iframe')
  const video = slide.querySelector('video')
  const url = frame.dataset.url

  fetch(url, { mode: 'no-cors', cache: 'no-store' })
    .then(() => {
      if (!frame.src) frame.src = url
      slide.classList.add('live')
      slide.classList.remove('offline')
    })
    .catch(() => {
      slide.classList.add('offline')
      slide.classList.remove('live')
      video.currentTime = 0
      video.play().catch(() => {})
    })

  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
  tl.from(slide.querySelectorAll('.kicker, .heading'), { y: 40, autoAlpha: 0, duration: 0.7, stagger: 0.1 })
    .from(slide.querySelector('.win'), { y: 120, scale: 0.94, autoAlpha: 0, duration: 1 }, 0.15)
  return tl
})
