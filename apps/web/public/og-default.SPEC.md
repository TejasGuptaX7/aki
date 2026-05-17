# Open Graph image — spec

The site currently generates `og:image` at build time from
`src/app/opengraph-image.tsx`. That's good enough for launch — it renders the
Glyph II identity with the Source Serif wordmark and the lime accent on the
dark background.

If you'd rather hand-design a static image (designer-polished kerning,
exported with Display P3 color, etc.), drop a file here:

    apps/web/src/app/opengraph-image.png

Next.js' file convention takes precedence over the route convention, so the
PNG will replace the generated image automatically — no code change needed.

## Spec

- **Dimensions**: 1200 × 630 (Facebook + Twitter "large summary" standard)
- **Format**: PNG (8MB max)
- **Color**: Display P3 if available, sRGB fallback
- **Background**: `#15161a` (theme.bg)
- **Accent**: `#c5ec4f` (theme.accent)
- **Primary type**: Source Serif 4, 700 weight
- **Secondary type**: Geist, 500 weight
- **Safe area**: keep critical content within a 1080 × 510 center region so
  Slack/Twitter cropping doesn't eat the wordmark

## Suggested layout

```
┌──────────────────────────────────────────────────────────────────┐
│  a aki                                          V 0.7 · PRIVATE BETA│
│                                                                    │
│                                                                    │
│   Hire your first                                                  │
│   tireless coworker.        ← lime accent on "tireless coworker"  │
│                                                                    │
│   Named agents your team can DM in Slack. Each one runs the work,  │
│   cites its sources, and asks before anything irreversible.        │
│                                                                    │
│  ────────────────────────────────────────────────────────────────  │
│  aki.dev                                       get on the beta →   │
└──────────────────────────────────────────────────────────────────┘
```

## Alt text

The generated image's alt text comes from the `alt` export in
`opengraph-image.tsx`. If you replace with a static PNG, also drop an
`opengraph-image.alt.txt` next to it:

    apps/web/src/app/opengraph-image.alt.txt
    > Aki — named agents your team can DM in Slack
