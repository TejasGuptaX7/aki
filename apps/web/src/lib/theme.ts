// Glyph II theme tokens — shared across the landing + app pages.
// Anything imported in 'use client' pages is fine here too (these are
// just constants).
export const theme = {
  bg: "#15161a",
  bgSoft: "#1d1f24",
  ink: "#f1ede0",
  inkLede: "#e3dcc5",
  inkDim: "rgba(241,237,224,0.66)",
  inkFaint: "rgba(241,237,224,0.36)",
  hair: "rgba(241,237,224,0.12)",
  hairSoft: "rgba(241,237,224,0.06)",
  accent: "#c5ec4f",
  accentDim: "rgba(197,236,79,0.18)",
  display: "var(--font-display), 'Times New Roman', serif",
  body: "var(--font-body), system-ui, sans-serif",
  mono: "var(--font-mono), ui-monospace, monospace",
};

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
