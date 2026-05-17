import { ImageResponse } from "next/og";

/**
 * Generated at build time by Next 16's opengraph-image convention. Renders
 * the Glyph II identity (dark bg, lime accent, big serif "a" + wordmark +
 * tagline). The founder can override with a hand-designed PNG by adding
 * `apps/web/src/app/opengraph-image.png` — file convention beats route
 * convention when both exist.
 *
 * Spec for the override is at `public/og-default.SPEC.md`.
 */

export const alt = "Aki — named agents your team can DM in Slack";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const ink = "#f1ede0";
const inkLede = "#e3dcc5";
const inkDim = "rgba(241,237,224,0.66)";
const inkFaint = "rgba(241,237,224,0.36)";
const bg = "#15161a";
const accent = "#c5ec4f";

export default async function Image() {
  // Satori needs at least one font loaded to render reliably. We pull the
  // Source Serif 4 + Geist Sans variants the rest of the brand uses from
  // Google Fonts at build time. Cached after first build by Next.
  const [serifBold, sansMedium] = await Promise.all([
    fetchFont("https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,700&display=swap"),
    fetchFont("https://fonts.googleapis.com/css2?family=Geist:wght@500&display=swap"),
  ]);

  return new ImageResponse(
    (
      <div style={{
        width: "100%", height: "100%",
        background: bg, color: ink,
        display: "flex", flexDirection: "column",
        padding: "72px 80px",
        position: "relative",
      }}>
        {/* top row: wordmark + kicker */}
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", fontFamily: "Geist",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <span style={{
              fontFamily: "Source Serif 4", fontSize: 80, lineHeight: 0.78,
              color: ink, letterSpacing: "-0.04em", fontWeight: 700,
            }}>a</span>
            <span style={{
              fontSize: 32, fontWeight: 500, letterSpacing: "0.04em",
              color: ink,
            }}>aki</span>
          </div>
          <span style={{
            fontSize: 18, color: inkFaint,
            letterSpacing: "0.24em", textTransform: "uppercase",
          }}>v 0.7 · private beta</span>
        </div>

        {/* center: tagline */}
        <div style={{
          display: "flex", flexDirection: "column",
          flex: 1, justifyContent: "center", marginTop: 48,
        }}>
          <div style={{
            fontFamily: "Source Serif 4", fontSize: 96, fontWeight: 700,
            color: ink, letterSpacing: "-0.025em", lineHeight: 1,
            display: "flex", flexDirection: "column",
          }}>
            <span>Hire your first</span>
            <span style={{ color: accent }}>tireless coworker.</span>
          </div>
          <div style={{
            marginTop: 32, fontFamily: "Geist", fontSize: 28,
            color: inkDim, lineHeight: 1.4, maxWidth: 920,
          }}>
            Named agents your team can DM in Slack. Each one runs the work,
            cites its sources, and asks before anything irreversible.
          </div>
        </div>

        {/* bottom: url */}
        <div style={{
          display: "flex", justifyContent: "space-between",
          alignItems: "center", borderTop: "1px solid rgba(241,237,224,0.18)",
          paddingTop: 24, fontFamily: "Geist", fontSize: 20,
          color: inkLede,
        }}>
          <span>aki.dev</span>
          <span style={{ color: accent, fontWeight: 500 }}>get on the beta →</span>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        ...(serifBold ? [{ name: "Source Serif 4", data: serifBold, style: "normal" as const, weight: 700 as const }] : []),
        ...(sansMedium ? [{ name: "Geist", data: sansMedium, style: "normal" as const, weight: 500 as const }] : []),
      ],
    },
  );
}

/**
 * Fetches a font binary from a Google Fonts CSS URL. Pulls the first
 * @font-face src in the stylesheet and returns its bytes. Returns null on
 * failure so the build still produces an image with satori's default font.
 */
async function fetchFont(googleCssUrl: string): Promise<ArrayBuffer | null> {
  try {
    const css = await fetch(googleCssUrl, {
      headers: { "User-Agent": "Mozilla/5.0" },
    }).then((r) => r.text());
    const url = css.match(/src: url\((https:[^)]+)\)/)?.[1];
    if (!url) return null;
    const res = await fetch(url);
    if (!res.ok) return null;
    return await res.arrayBuffer();
  } catch {
    return null;
  }
}
