import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { theme } from "../lib/theme";
import { CopyIcon } from "./CopyIcon";
import { ToolPanel } from "./ToolPanel";
import type { Msg } from "../hooks/useChat";

export function MessageBlock({ msg }: { msg: Msg }) {
  const isUser = msg.role === "user";
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(msg.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* ignore */
    }
  }

  return (
    <div style={{ marginBottom: 28 }}>
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 10,
          color: isUser ? theme.inkDim : theme.accent,
          letterSpacing: "0.22em",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        {isUser ? "you" : "aki"}
      </div>

      <div
        style={{
          fontFamily: theme.body,
          fontSize: 16,
          lineHeight: 1.6,
          color: isUser ? theme.inkLede : theme.ink,
          wordBreak: "break-word",
        }}
      >
        {isUser ? (
          <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>
        ) : msg.content ? (
          <MarkdownContent content={msg.content} />
        ) : (
          <span style={{ color: theme.inkFaint }}>…</span>
        )}
      </div>

      {msg.tools && msg.tools.length > 0 && <ToolPanel tools={msg.tools} />}

      {!isUser && msg.content && (
        <div
          style={{
            marginTop: 12,
            display: "flex",
            gap: 14,
            alignItems: "center",
          }}
        >
          <button
            onClick={copy}
            style={{
              background: "transparent",
              border: "none",
              padding: 0,
              cursor: "pointer",
              fontFamily: theme.mono,
              fontSize: 11,
              color: copied ? theme.accent : theme.inkFaint,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <CopyIcon /> {copied ? "copied" : "copy"}
          </button>
          <span
            style={{
              fontFamily: theme.mono,
              fontSize: 11,
              color: theme.inkFaint,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
            }}
          >
            · done
          </span>
        </div>
      )}
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => (
          <p style={{ margin: "0 0 0.75em 0", lineHeight: 1.6 }}>{children}</p>
        ),
        pre: ({ children }) => (
          <pre
            style={{
              background: theme.bgSoft,
              padding: 12,
              borderRadius: 4,
              overflow: "auto",
              border: `1px solid ${theme.hair}`,
              margin: "0 0 0.75em 0",
            }}
          >
            {children}
          </pre>
        ),
        code: ({ children, className }) => {
          const isInline = !className;
          return (
            <code
              style={{
                fontFamily: theme.mono,
                fontSize: isInline ? "0.9em" : 13,
                background: isInline ? theme.bgSoft : "transparent",
                padding: isInline ? "2px 4px" : 0,
                borderRadius: isInline ? 3 : 0,
                color: theme.inkLede,
              }}
            >
              {children}
            </code>
          );
        },
        ul: ({ children }) => (
          <ul style={{ margin: "0 0 0.75em 0", paddingLeft: 20 }}>{children}</ul>
        ),
        ol: ({ children }) => (
          <ol style={{ margin: "0 0 0.75em 0", paddingLeft: 20 }}>{children}</ol>
        ),
        li: ({ children }) => (
          <li style={{ marginBottom: 4 }}>{children}</li>
        ),
        h1: ({ children }) => (
          <h1
            style={{
              fontSize: 20,
              fontWeight: 600,
              margin: "0 0 0.5em 0",
              color: theme.ink,
            }}
          >
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2
            style={{
              fontSize: 18,
              fontWeight: 600,
              margin: "0 0 0.5em 0",
              color: theme.ink,
            }}
          >
            {children}
          </h2>
        ),
        h3: ({ children }) => (
          <h3
            style={{
              fontSize: 16,
              fontWeight: 600,
              margin: "0 0 0.5em 0",
              color: theme.ink,
            }}
          >
            {children}
          </h3>
        ),
        a: ({ children, href }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: theme.accent, textDecoration: "underline" }}
          >
            {children}
          </a>
        ),
        blockquote: ({ children }) => (
          <blockquote
            style={{
              borderLeft: `2px solid ${theme.accentDim}`,
              margin: "0 0 0.75em 0",
              paddingLeft: 12,
              color: theme.inkDim,
            }}
          >
            {children}
          </blockquote>
        ),
        hr: () => (
          <hr
            style={{
              border: "none",
              borderTop: `1px solid ${theme.hair}`,
              margin: "1em 0",
            }}
          />
        ),
        table: ({ children }) => (
          <table
            style={{
              borderCollapse: "collapse",
              width: "100%",
              marginBottom: "0.75em",
              fontSize: 14,
            }}
          >
            {children}
          </table>
        ),
        th: ({ children }) => (
          <th
            style={{
              border: `1px solid ${theme.hair}`,
              padding: "6px 10px",
              textAlign: "left",
              fontWeight: 600,
              background: theme.bgSoft,
            }}
          >
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td
            style={{
              border: `1px solid ${theme.hair}`,
              padding: "6px 10px",
              textAlign: "left",
            }}
          >
            {children}
          </td>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
