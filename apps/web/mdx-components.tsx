import type { MDXComponents } from "mdx/types";
import Link from "next/link";
import * as React from "react";

/**
 * MDX → Glyph II mapping. Inline styles intentional so docs match the
 * rest of the surfaces without depending on a parallel CSS file.
 */
const ink = "#f1ede0";
const inkLede = "#e3dcc5";
const inkDim = "rgba(241,237,224,0.66)";
const inkFaint = "rgba(241,237,224,0.36)";
const hair = "rgba(241,237,224,0.12)";
const bgSoft = "#1d1f24";
const accent = "#c5ec4f";
const display = "var(--font-display), 'Times New Roman', serif";
const body = "var(--font-body), system-ui, sans-serif";
const mono = "var(--font-mono), ui-monospace, monospace";

const components: MDXComponents = {
  h1: ({ children, ...rest }) => (
    <h1 {...rest} style={{
      fontFamily: display, fontWeight: 600, fontSize: 44,
      letterSpacing: "-0.025em", lineHeight: 1.05,
      margin: "8px 0 18px", color: ink,
    }}>{children}</h1>
  ),
  h2: ({ children, ...rest }) => (
    <h2 {...rest} style={{
      fontFamily: display, fontWeight: 600, fontSize: 30,
      letterSpacing: "-0.02em", lineHeight: 1.1,
      margin: "48px 0 16px", color: ink, scrollMarginTop: 90,
    }}>{children}</h2>
  ),
  h3: ({ children, ...rest }) => (
    <h3 {...rest} style={{
      fontFamily: display, fontWeight: 600, fontSize: 22,
      letterSpacing: "-0.015em", lineHeight: 1.2,
      margin: "32px 0 12px", color: ink, scrollMarginTop: 90,
    }}>{children}</h3>
  ),
  p: ({ children, ...rest }) => (
    <p {...rest} style={{
      fontFamily: body, fontSize: 16, lineHeight: 1.6,
      color: inkLede, margin: "0 0 18px",
    }}>{children}</p>
  ),
  ul: ({ children, ...rest }) => (
    <ul {...rest} style={{
      fontFamily: body, fontSize: 16, lineHeight: 1.6,
      color: inkLede, margin: "0 0 18px 0", paddingLeft: 22,
    }}>{children}</ul>
  ),
  ol: ({ children, ...rest }) => (
    <ol {...rest} style={{
      fontFamily: body, fontSize: 16, lineHeight: 1.6,
      color: inkLede, margin: "0 0 18px 0", paddingLeft: 22,
    }}>{children}</ol>
  ),
  li: ({ children, ...rest }) => (
    <li {...rest} style={{ marginBottom: 6 }}>{children}</li>
  ),
  a: ({ children, href = "", ...rest }) => {
    const external = /^https?:/.test(href);
    const style: React.CSSProperties = {
      color: accent, textDecoration: "underline",
      textDecorationColor: "rgba(197,236,79,0.4)",
      textUnderlineOffset: 3,
    };
    if (external) {
      return <a href={href} {...rest} target="_blank" rel="noreferrer" style={style}>{children}</a>;
    }
    return <Link href={href} style={style}>{children}</Link>;
  },
  strong: ({ children, ...rest }) => (
    <strong {...rest} style={{ color: ink, fontWeight: 600 }}>{children}</strong>
  ),
  em: ({ children, ...rest }) => (
    <em {...rest} style={{ fontStyle: "italic", color: inkLede }}>{children}</em>
  ),
  blockquote: ({ children, ...rest }) => (
    <blockquote {...rest} style={{
      margin: "20px 0", padding: "14px 18px",
      background: bgSoft, borderLeft: `2px solid ${accent}`,
      fontFamily: display, fontStyle: "italic", fontWeight: 500,
      fontSize: 17, lineHeight: 1.55, color: inkLede,
    }}>{children}</blockquote>
  ),
  code: (props) => {
    const { children, className, ...rest } = props as React.HTMLAttributes<HTMLElement>;
    // Block-level <code> inside <pre> arrives without a className; we leave
    // styling to <pre> below. Inline <code> gets the chip treatment.
    if (className && className.startsWith("language-")) {
      return <code className={className} {...rest}>{children}</code>;
    }
    return (
      <code {...rest} style={{
        fontFamily: mono, fontSize: 13,
        background: bgSoft, color: inkLede,
        padding: "2px 6px", borderRadius: 4,
        border: `1px solid ${hair}`,
      }}>{children}</code>
    );
  },
  pre: ({ children, ...rest }) => (
    <pre {...rest} style={{
      margin: "16px 0 24px", padding: "16px 18px",
      background: bgSoft, border: `1px solid ${hair}`, borderRadius: 4,
      fontFamily: mono, fontSize: 13, lineHeight: 1.55,
      color: inkLede,
      overflowX: "auto",
    }}>{children}</pre>
  ),
  hr: () => <hr style={{
    border: "none", borderTop: `1px solid ${hair}`, margin: "40px 0",
  }}/>,
  table: ({ children, ...rest }) => (
    <div style={{ overflowX: "auto", margin: "16px 0 24px" }}>
      <table {...rest} style={{
        width: "100%", borderCollapse: "collapse",
        fontFamily: body, fontSize: 14, color: inkLede,
      }}>{children}</table>
    </div>
  ),
  th: ({ children, ...rest }) => (
    <th {...rest} style={{
      textAlign: "left", padding: "10px 12px",
      borderBottom: `1px solid ${hair}`,
      fontFamily: mono, fontSize: 10, color: inkFaint,
      letterSpacing: "0.18em", textTransform: "uppercase", fontWeight: 500,
    }}>{children}</th>
  ),
  td: ({ children, ...rest }) => (
    <td {...rest} style={{
      padding: "10px 12px", borderBottom: `1px solid ${hair}`,
      verticalAlign: "top",
    }}>{children}</td>
  ),
};

export function useMDXComponents(): MDXComponents {
  return components;
}

export { inkDim, inkFaint };
