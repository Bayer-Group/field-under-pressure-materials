# Field explorer showcase video (30 s, written in code)

Output: `field-explorer-showcase.mp4` (1920×1080, 30 fps, H.264 + AAC).

| File | What it does |
|---|---|
| `capture.mjs` | Drives the running GUI in headless Chromium, saves real screens to `shots/` and the positions of key elements to `shots/rects.js` |
| `video.html` | The video itself. Every frame is a pure function of time (`seek(t)`). Open it in a browser to preview: Space pauses, ←/→ step a frame, click the bar to scrub, `?t=12` starts at 12 s |
| `music.mjs` | Synthesizes the soundtrack (120 bpm, Am–F–C–G, whooshes on every scene cut) |
| `render.mjs` | Steps `seek()` through all 900 frames and pipes them into ffmpeg with the soundtrack |
| `cdp.mjs` | Minimal Chrome DevTools Protocol client (no npm dependencies) |

Rebuild (needs `chromium`, `ffmpeg`, Node ≥ 22, and the GUI running with a current `web/dist`):

```bash
node showcase/capture.mjs http://127.0.0.1:8000
node showcase/render.mjs                         # ~1.5 min
node showcase/render.mjs --stills 5,10.5,20      # quick PNG checks in showcase/stills/
```

Storyboard: 0–4 s logo and beat-synced word flashes · 4–8 overview map (29 plots, 2 sites) · 8–12 greenness timeline ·
12–14 aerial photo vs greenness map · 14–18 soil microbes · 18–21 soil function cards · 21–24 nitrogen cycle ·
24–26 sampling visit page · 26–30 outro.
