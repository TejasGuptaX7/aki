import { invoke } from "@tauri-apps/api/core";
import { theme } from "../lib/theme";

export function ChatInput({
  input,
  onChange,
  onSend,
  pending,
}: {
  input: string;
  onChange: (v: string) => void;
  onSend: () => void;
  pending: boolean;
}) {
  const saveNote = async () => {
    if (!input.trim()) return;
    try {
      await invoke("add_journal_note", {
        kind: "note",
        title: input.trim().split("\n")[0].slice(0, 120),
        content: input.trim(),
      });
    } catch (e) {
      console.error("Failed to save journal note:", e);
    }
  };
  const lines = input.split("\n").length;
  const rows = Math.min(Math.max(lines, 2), 8);

  return (
    <div style={{ borderTop: `1px solid ${theme.hair}`, padding: "20px 0" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 32px" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder="Ask Aki to do something with your connected tools…"
            disabled={pending}
            rows={rows}
            style={{
              flex: 1,
              resize: "none",
              background: theme.bgSoft,
              color: theme.ink,
              border: `1px solid ${theme.hair}`,
              borderRadius: 6,
              padding: "12px 14px",
              fontFamily: theme.body,
              fontSize: 15,
              lineHeight: 1.45,
              outline: "none",
            }}
          />
          <button
            onClick={saveNote}
            disabled={pending || !input.trim()}
            title="Save to journal"
            style={{
              background: "transparent",
              color: theme.inkDim,
              border: `1px solid ${theme.hair}`,
              fontFamily: theme.body,
              fontWeight: 500,
              fontSize: 12,
              padding: "12px 14px",
              borderRadius: 999,
              cursor: pending ? "default" : "pointer",
              opacity: pending || !input.trim() ? 0.4 : 1,
            }}
          >
            Save
          </button>
          <button
            onClick={onSend}
            disabled={pending || !input.trim()}
            style={{
              background: theme.accent,
              color: theme.bg,
              border: "none",
              fontFamily: theme.body,
              fontWeight: 600,
              fontSize: 14,
              padding: "12px 22px",
              borderRadius: 999,
              cursor: pending ? "default" : "pointer",
              opacity: pending || !input.trim() ? 0.5 : 1,
            }}
          >
            {pending ? "…" : "Send"}
          </button>
        </div>
        <div
          style={{
            marginTop: 8,
            fontFamily: theme.mono,
            fontSize: 10,
            color: theme.inkFaint,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
          }}
        >
          enter to send · shift+enter for newline · save to journal
        </div>
      </div>
    </div>
  );
}
