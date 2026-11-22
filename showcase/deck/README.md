# Terranos presentation (reveal.js + GSAP)

A slide deck that runs in the browser. reveal.js handles navigation, speaker notes, the overview and PDF export. GSAP handles the animations. No build step and no network: all libraries are copied into `vendor/`.

## Run it

The video `../terranos-showcase.mp4` (shown in the demo break) is generated, so it isn't in git. On a fresh clone, start the GUI and render it first (see `../README.md`):

```bash
node showcase/capture.mjs http://127.0.0.1:8000
node showcase/render.mjs
```

Serve the `showcase` folder, not just `deck`, because the demo break loads `../terranos-showcase.mp4`:

```bash
python3 -m http.server 8090 --bind 127.0.0.1 --directory showcase
```

Then open <http://127.0.0.1:8090/deck/>. In the desktop app, the `deck` entry in `.claude/launch.json` does the same thing.

Opening `index.html` directly from disk also works, but the speaker view behaves better over http.

The demo break plays the video with sound. It starts by itself when you arrive on the slide with a key press or click; if the browser blocks sound, it plays muted.

| Key | Action |
|---|---|
| → / Space | Next step or slide |
| ← | Back |
| R | Replay the current slide's animation |
| S | Speaker view (notes, timer, next slide) |
| O / Esc | Overview of all slides |
| F | Fullscreen |
| B | Blank the screen |

## Export a folder to send

When the slides are done, run:

```bash
node showcase/export.mjs          # -> showcase/export/terranos-deck/
node showcase/export.mjs --zip    # also -> showcase/export/terranos-deck.zip
```

The folder holds `deck/`, `brand/`, the video, a short `README.txt` with the keys, and an `Open presentation.html` launcher. It opens from disk with no server or internet. The script stops if the video is missing. It warns if `video.html`, `music.mjs`, `shots/` or `brand/` changed since the video was rendered (`render.mjs` records a hash of them in `terranos-showcase.mp4.sources`), if the page references a file outside the export, or if a `todo` marker is left. `showcase/export/` is ignored by git.

Fonts aren't bundled: the slides use Inter or Roboto if installed, else the system font.

To get a PDF, open `http://127.0.0.1:8090/deck/?print-pdf` in Chromium and print it to PDF (landscape, no margins, background graphics on). Every animated slide is shown in its final state.

## Files

| File | What it is |
|---|---|
| `index.html` | The slides. Each `<section>` is one slide |
| `css/theme.css` | Colors, type, background, logo and shared components (same palette as `../video.html`) |
| `css/story.css` | Layout of each slide |
| `js/data.js` | Content the animations read: sequencing cost, PubMed counts, soil groups |
| `js/engine.js` | Connects reveal.js and GSAP: builds, plays, steps through and resets each slide's animation |
| `js/earth.js` | The spinning Earth in the title logo (a canvas drawn with d3-geo) |
| `js/anims/story.js` | Each slide's animation, and the line icons |
| `js/anims/basic.js` | Generic `text` slide animation |
| `vendor/` | reveal.js 6.0.2, GSAP 3.15.1, and d3-geo + topojson-client + world-atlas land outlines for the spinning Earth (copied from npm) |

## Slide order

| # | Section | Slides (`data-anim`) |
|---|---|---|
| 0 | Title | `collide`: Geoinformatics ⇒ Terranos ⇐ Bioinformatics |
| 1 | The problem | `genomics` (geoinformatic data → genomics) · `meta` (what is metagenomics) · `trend` (cost per genome vs papers) · `merge` (metagenomics + geoinformation) |
| 2 | Goal | `goal` (sowing, fertilization, spraying → biological balance) · `timeline` (history → now → future) |
| 3 | Data | `stack` (shotgun sequencing, NDVI, geochemistry, qPCR) |
| 4 | Demo | `reel`: a short break that plays `../terranos-showcase.mp4` full screen |
| 5 | Already done | `done` (soil microbes, soil characteristics, crop disease risk, treatment) |
| 6 | Future | `future` (agro-chemical branch, EU sustainability) |
| | Outro | `finale` |

## How a slide animates

1. Give the slide `data-anim="<name>"`.
2. Register a builder: `Deck.anim('<name>', (slide, Deck) => timeline)`. It runs every time the slide is entered. Everything it animates is reset after you leave, so each visit starts fresh.
3. For click-by-click steps, add one empty `<i class="fragment step"></i>` per click, and put the labels `step1`, `step2`, … into the timeline. Entering the slide plays up to `step1`, and each click plays to the next label. Going back rewinds.

Plain reveal.js fragments (`class="fragment fade-up"`) still work alongside these steps.

### Reusable slide types

- **`text`**: the heading's words rise into place, followed by every element with the `.rise` class.

## Before presenting

- Search for `todo` in `index.html`. Orange TODO badges mark placeholder content (they're hidden in the PDF but not on screen).
- The `meta` and `value` slides use **illustrative** soil shares and a schematic field (`DeckData.taxa`, `value` in `story.js`). The `trend` chart is real data (NHGRI, PubMed); re-run the PubMed counts before presenting if the date has moved on.
- Check the room's audio for the demo break: the video has a soundtrack.
- Rehearse on the laptop and projector you'll use. Animations only move `transform` and `opacity`, and the background avoids `filter: blur`, so it should stay smooth on modest hardware.
- When the viewer's OS asks for reduced motion, every step jumps straight to its end state.
