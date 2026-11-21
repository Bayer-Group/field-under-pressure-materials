# Terranos presentation (reveal.js + GSAP)

A slide deck that runs in the browser. reveal.js handles navigation, speaker notes, the overview and PDF export. GSAP handles the animations. No build step and no network: both libraries are copied into `vendor/`.

## Run it

The screenshots in `../shots/` and the video `../terranos-showcase.mp4` are generated, so they aren't in git. On a fresh clone, start the GUI and create them first (see `../README.md`):

```bash
node showcase/capture.mjs http://127.0.0.1:8000
node showcase/render.mjs
```

Serve the `showcase` folder, not just `deck`, because the slides load the GUI screenshots from `../shots/`:

```bash
python3 -m http.server 8090 --bind 127.0.0.1 --directory showcase
```

Then open <http://127.0.0.1:8090/deck/>. In the desktop app, the `deck` entry in `.claude/launch.json` does the same thing.

Opening `index.html` directly from disk also works, but the speaker view and the live demo slide behave better over http.

For the live demo slide, also start the GUI on port 8000 (launch config `gui`). If the GUI isn't running, that slide plays `../terranos-showcase.mp4` instead.

| Key | Action |
|---|---|
| → / Space | Next step or slide |
| ← | Back |
| R | Replay the current slide's animation |
| S | Speaker view (notes, timer, next slide) |
| O / Esc | Overview of all slides |
| F | Fullscreen |
| B | Blank the screen |

To get a PDF, open `http://127.0.0.1:8090/deck/?print-pdf` in Chromium and print it to PDF (landscape, no margins, background graphics on). Every animated slide is shown in its final state.

## Files

| File | What it is |
|---|---|
| `index.html` | The slides. Each `<section>` is one slide |
| `css/theme.css` | Colors, type and per-slide layout (same palette as `../video.html`) |
| `js/data.js` | Content the animations read: data sources, sites, chart data, nitrogen cycle |
| `js/engine.js` | Connects reveal.js and GSAP: builds, plays, steps through and resets each slide's animation |
| `js/anims/*.js` | One animation per slide type |
| `vendor/` | reveal.js 6.0.2 and GSAP 3.15.1 (copied from npm) |

## How a slide animates

1. Give the slide `data-anim="<name>"`.
2. Register a builder: `Deck.anim('<name>', (slide, Deck) => timeline)`. It runs every time the slide is entered. Everything it animates is reset after you leave, so each visit starts fresh.
3. For click-by-click steps, add one empty `<i class="fragment step"></i>` per click, and put the labels `step1`, `step2`, … into the timeline. Entering the slide plays up to `step1`, and each click plays to the next label. Going back rewinds.

Plain reveal.js fragments (`class="fragment fade-up"`) still work alongside these steps (see slide 2).

### Reusable slide types

- **`gui`**: a browser window around a real screenshot that zooms onto captured elements. Steps use `data-focus="<rect key>:<index>"` from `../shots/rects.json` (or `all`) and an optional `data-caption`. To add a screen, capture it with `../capture.mjs`, then copy a `gui` section and change `data-shot`.
- **`wipe`**: a before/after slider between two screenshot crops (`data-under`, `data-over`). The presenter can drag the handle.
- **`text`**: the heading's words rise into place, followed by every element with the `.rise` class.

## Before presenting

- Search for `todo` in `index.html`. Orange TODO badges mark placeholder content (they're hidden in the PDF but not on screen).
- Slide 6 uses an **illustrative** greenness curve. Replace `DeckData.greenness` in `js/data.js` with a real plot-year.
- Slide 8: `greenness.png` and `greenness-map.png` were captured at different map zoom levels, so the wipe doesn't line up. Capture both map layers at the same zoom.
- Rehearse on the laptop and projector you'll use. Animations only move `transform` and `opacity`, and the background avoids `filter: blur`, so it should stay smooth on modest hardware.
- When the viewer's OS asks for reduced motion, every step jumps straight to its end state.
