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
  display: "'Source Serif 4', 'Times New Roman', serif",
  body: "'Geist', system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
} as const

export const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"
