import { theme } from "../lib/theme";

export function EmptyChat({ onPick }: { onPick: (text: string) => void }) {
  const examples = [
    "List my 5 most recent emails — just sender and subject.",
    "Find anything about 'invoice' from the last 14 days.",
    "Use code execution to compute fibonacci(20).",
  ];

  return (
    <div style={{ paddingTop: 80, textAlign: "center" }}>
      <div
        style={{
          fontFamily: theme.display,
          fontStyle: "italic",
          fontSize: 36,
          fontWeight: 500,
          letterSpacing: "-0.02em",
          color: theme.inkLede,
          marginBottom: 32,
        }}
      >
        Ask Aki something.
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          maxWidth: 560,
          margin: "0 auto",
        }}
      >
        {examples.map((e) => (
          <button
            key={e}
            onClick={() => onPick(e)}
            style={{
              padding: "12px 16px",
              background: "transparent",
              border: `1px dashed ${theme.hair}`,
              color: theme.inkDim,
              fontFamily: theme.body,
              fontSize: 14,
              textAlign: "left",
              cursor: "pointer",
              transition: "border-color 0.15s ease, color 0.15s ease",
            }}
            onMouseEnter={(e2) => {
              e2.currentTarget.style.borderColor = theme.accent;
              e2.currentTarget.style.color = theme.ink;
            }}
            onMouseLeave={(e2) => {
              e2.currentTarget.style.borderColor = theme.hair;
              e2.currentTarget.style.color = theme.inkDim;
            }}
          >
            {e}
          </button>
        ))}
      </div>
    </div>
  );
}
