# Shader Painting Frontend Template

A long-scroll brutalist exhibition / gallery site with three cinematic sections:

1. **Hero** — full-viewport WebGL shader applied to a source image (noise-displaced UVs → oil-painting fluid flow), with a typewritten subtitle and a CTA button.
2. **Selected Works** — 4-column parallax grid of clickable cards. Each card opens a dedicated detail page with a large image and an article.
3. **The Instant** — a kinetic-text section over a looping background video (3 staggered lines that reveal on scroll).

Everything is config-driven via `src/config.ts`. Components read from config and render `null` when required fields are empty.

## Features

- WebGL fluid-flow shader on a static hero image (simplex noise UV displacement)
- Typewriter subtitle + glass-morphism CTA
- Parallax 4-column card grid with mild scroll-driven offsets
- Clickable cards → detail page (`/work/:id`) with large image + article
- Kinetic text section with staggered translate-up reveals over video
- Custom cursor (active on all routes)
- React Router v7 for the gallery / work-detail split
- Optimized card images (srcset, lazy, decoding async, content-visibility)

## Tech Stack

- React 19 + TypeScript + Vite
- Tailwind CSS v3 (utility only, mostly unused)
- Three.js for the fluid shader + the cascade's ambient mesh
- GSAP + ScrollTrigger for parallax
- `react-router` v7

## Quick Start

1. `npm install`
2. Edit `src/config.ts` with your content
3. Add images to `public/images/`, videos to `public/videos/`
4. `npm run dev`
5. `npm run build`

## Configuration

All editable content lives in `src/config.ts`. See `info.md` at the outer wrapper level for the full field-by-field documentation.

## Required Images

Put files in `public/images/`:

- **`<heroConfig.fluidImagePath>`** — full-viewport Hero source image. High-res, any aspect ratio (the shader covers). Something painterly works well.

All card images in the gallery are loaded from external URLs using the `seed` field: `https://picsum.photos/seed/{seed}/480/320`. If you want to use your own hosted images instead, replace the `<img src>` in `src/sections/GenerativeCascade.tsx` and `src/pages/WorkDetail.tsx`.

## Required Videos

Put files in `public/videos/`:

- **`<instantConfig.videoPath>`** — background loop for the kinetic-text section. Keep it dark/abstract; the text sits on top. ~8–15 seconds loops well.

## Design Reference

- Background: `#000000` (hero / footer) and `#ffffff` (gallery)
- Text: white on dark, black on white
- Typefaces: `Geist Mono` (display), `Inter` (body), `Space Mono` (labels)
- Motion: parallax (mild, 4–12%), typewriter reveal, kinetic text
- Shader colors: controlled by the hero image itself — the shader distorts UVs, not color

## Build

```bash
npm run build
```

Output in `dist/`.

## Project Structure

```
8-liquit-paint-frontend/
├── README.md
├── package.json
├── index.html
├── vite.config.ts
├── tailwind.config.js
├── public/
│   ├── images/.gitkeep      # add hero source image here
│   └── videos/.gitkeep      # add ambient video here
└── src/
    ├── config.ts            # ⭐ ALL content lives here
    ├── main.tsx             # BrowserRouter + root
    ├── App.tsx              # Routes: / and /work/:id
    ├── index.css / App.css  # base styles
    ├── pages/
    │   ├── Home.tsx         # Hero → Gallery → Instant → Footer
    │   └── WorkDetail.tsx   # large image + article
    ├── sections/
    │   ├── FluidSubconscious.tsx  # WebGL shader on hero image (logic, no content)
    │   ├── HeroOverlay.tsx        # reads heroConfig
    │   ├── GenerativeCascade.tsx  # reads galleryConfig
    │   ├── DeepSpaceFold.tsx      # reads instantConfig
    │   └── CustomCursor.tsx       # cursor behaviour, no content
    ├── components/ui/       # shadcn kit, mostly unused
    ├── hooks/
    └── lib/
```

## Notes

- All content is in `src/config.ts` — do not edit components unless fixing a bug.
- If `galleryConfig.works` is empty, the gallery section renders `null`.
- If `heroConfig.fluidImagePath` is empty, the hero background is plain black (no shader).
- If `instantConfig.videoPath` is empty, the Instant section still renders but over black.
- The card image URL pattern (`https://picsum.photos/seed/...`) is easy to swap to any CDN.
- `FluidSubconscious.tsx` is hand-tuned; `uIntensity` controls distortion strength.
