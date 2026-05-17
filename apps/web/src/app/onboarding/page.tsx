"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { ErrorBanner } from "@/components/AppShell";
import { useAgents, useAuthToken, rememberAgent } from "@/lib/agents";
import { agentsApi } from "@/lib/api";

/**
 * First-run wizard. Three plain-English answers compose into a system
 * prompt; we create the agent and drop the user into /chat/[id].
 *
 * Also reachable later from /agents → "+ New" for a guided alternative
 * to the quick-create modal.
 */
export default function OnboardingPage() {
  const router = useRouter();
  const tok = useAuthToken();
  const { agents, status, refresh } = useAgents();
  const [name, setName] = React.useState("");
  const [who, setWho] = React.useState("");
  const [tools, setTools] = React.useState("");
  const [task, setTask] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  // Heuristic name fallback: extract from "who" if name field is blank
  const composed = React.useMemo(() => composeSystemPrompt({ name, who, tools, task }), [name, who, tools, task]);
  const ready = who.trim().length > 8;

  async function submit() {
    if (!ready || busy) return;
    setBusy(true); setErr(null);
    try {
      const finalName = name.trim() || deriveName(who) || "Aki";
      const created = await agentsApi.create(tok, {
        name: finalName,
        system_prompt: composed,
      });
      rememberAgent(created.id);
      await refresh();
      router.replace(`/chat/${created.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh", background: theme.bg, color: theme.ink,
      fontFamily: theme.body, display: "flex", flexDirection: "column",
    }}>
      <header style={{
        padding: "32px 56px", borderBottom: `1px solid ${theme.hair}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{
            fontFamily: theme.display, fontWeight: 700, fontSize: 34,
            lineHeight: 0.78, letterSpacing: "-0.04em",
          }}>a</span>
          <span style={{ fontFamily: theme.body, fontWeight: 600, fontSize: 16, letterSpacing: "0.04em" }}>aki</span>
        </div>
        {status === "ready" && agents.length > 0 && (
          <button onClick={() => router.push("/agents")} style={skipBtn}>
            Skip · go to agents
          </button>
        )}
      </header>

      <main style={{
        flex: 1, padding: "64px 56px", maxWidth: 820, width: "100%",
        margin: "0 auto", boxSizing: "border-box",
      }}>
        <div style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint,
          letterSpacing: "0.24em", textTransform: "uppercase", marginBottom: 14,
        }}>
          {agents.length === 0 ? "first agent" : "new agent"}
        </div>
        <h1 style={{
          margin: 0, fontFamily: theme.display, fontWeight: 600,
          fontSize: 48, lineHeight: 1.05, letterSpacing: "-0.025em",
        }}>
          Tell Aki what to be.
        </h1>
        <p style={{
          margin: "16px 0 0", fontFamily: theme.body, fontSize: 16,
          color: theme.inkLede, lineHeight: 1.5, maxWidth: 600,
        }}>
          Three answers in plain English. We'll compose the system prompt and spin up the agent.
          You can edit everything later.
        </p>

        {err && <div style={{ marginTop: 24 }}><ErrorBanner>{err}</ErrorBanner></div>}

        <div style={{ marginTop: 48, display: "flex", flexDirection: "column", gap: 32 }}>
          <Field n={1} label="Give it a name" hint="Short and human — 'Aki Sales', 'Aki Recruiting', 'Aki Ops'.">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Aki Sales"
              style={inputStyle}
            />
          </Field>

          <Field n={2} label="Who is this agent?" hint="Role, team, scope. The more grounded, the better.">
            <textarea
              value={who}
              onChange={(e) => setWho(e.target.value)}
              placeholder="A teammate for the SDR team. Handles inbound demo requests, qualifies them against our ICP, and books meetings on the AE calendar."
              rows={3}
              style={textareaStyle}
            />
          </Field>

          <Field n={3} label="What tools does it need?" hint="Free-form. We'll surface matching connections after.">
            <textarea
              value={tools}
              onChange={(e) => setTools(e.target.value)}
              placeholder="Gmail to read and reply. Google Calendar to book. Salesforce to log activity. Browser mode for everything else."
              rows={3}
              style={textareaStyle}
            />
          </Field>

          <Field n={4} label="What's its first task?" hint="A concrete first job so the agent has a north star.">
            <textarea
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Triage the inbound demo requests in inbox label 'sales/new' from the last 48 hours. Reply to qualified ones with a calendar link."
              rows={3}
              style={textareaStyle}
            />
          </Field>

          <details style={{
            background: theme.bgSoft, border: `1px solid ${theme.hair}`,
            padding: "14px 18px",
          }}>
            <summary style={{
              cursor: "pointer", fontFamily: theme.mono, fontSize: 11,
              color: theme.inkDim, letterSpacing: "0.18em", textTransform: "uppercase",
            }}>preview composed brief</summary>
            <pre style={{
              marginTop: 14, fontFamily: theme.mono, fontSize: 12,
              color: theme.inkLede, lineHeight: 1.55,
              whiteSpace: "pre-wrap", margin: 0,
            }}>{composed}</pre>
          </details>

          <div style={{ display: "flex", gap: 12, alignItems: "center", paddingTop: 8 }}>
            <button onClick={submit} disabled={!ready || busy} style={{
              ...primaryBtn, opacity: !ready || busy ? 0.5 : 1,
            }}>
              {busy ? "Creating agent…" : "Create agent"}
            </button>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.18em", textTransform: "uppercase",
            }}>
              {ready ? "ready" : "fill in 'who' to continue"}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function Field({ n, label, hint, children }: {
  n: number; label: string; hint: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div style={{ display: "flex", gap: 14, alignItems: "baseline", marginBottom: 10 }}>
        <span style={{
          fontFamily: theme.mono, fontSize: 11, color: theme.accent,
          letterSpacing: "0.18em",
        }}>{String(n).padStart(2, "0")}</span>
        <span style={{
          fontFamily: theme.display, fontSize: 22, fontWeight: 600,
          letterSpacing: "-0.015em",
        }}>{label}</span>
      </div>
      <div style={{
        marginBottom: 10, fontFamily: theme.body, fontSize: 13,
        color: theme.inkDim, lineHeight: 1.5, paddingLeft: 30,
      }}>{hint}</div>
      <div style={{ paddingLeft: 30 }}>{children}</div>
    </div>
  );
}

function composeSystemPrompt({ name, who, tools, task }: {
  name: string; who: string; tools: string; task: string;
}): string {
  const lines: string[] = [];
  const n = name.trim() || "Aki";
  lines.push(`You are ${n}, an autonomous Aki agent.`);
  lines.push("");
  if (who.trim()) {
    lines.push("ROLE");
    lines.push(who.trim());
    lines.push("");
  }
  if (tools.trim()) {
    lines.push("TOOLS YOU SHOULD EXPECT");
    lines.push(tools.trim());
    lines.push("");
  }
  if (task.trim()) {
    lines.push("FIRST TASK");
    lines.push(task.trim());
    lines.push("");
  }
  lines.push("OPERATING PRINCIPLES");
  lines.push("- Cite the source of every fact. Reference the email, ticket, or doc you used.");
  lines.push("- Ask for approval before sending anything outbound or making spend decisions.");
  lines.push("- If a tool is missing, say so plainly and suggest which connection would unblock you.");
  return lines.join("\n");
}

function deriveName(who: string): string | null {
  const first = who.trim().split(/[.\n]/)[0] ?? "";
  const m = first.match(/\b(sales|recruiting|ops|support|marketing|finance|legal|research|product)\b/i);
  if (m) return `Aki ${cap(m[1])}`;
  return null;
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

const inputStyle: React.CSSProperties = {
  width: "100%", background: theme.bgSoft, color: theme.ink,
  border: `1px solid ${theme.hair}`, borderRadius: 6,
  padding: "12px 14px", fontFamily: theme.body, fontSize: 15,
  outline: "none", boxSizing: "border-box",
};

const textareaStyle: React.CSSProperties = {
  ...inputStyle, fontFamily: theme.body, fontSize: 15, lineHeight: 1.5,
  resize: "vertical",
};

const primaryBtn: React.CSSProperties = {
  background: theme.accent, color: theme.bg, border: "none",
  fontFamily: theme.body, fontWeight: 600, fontSize: 14,
  padding: "12px 26px", borderRadius: 999, cursor: "pointer",
};

const skipBtn: React.CSSProperties = {
  background: "transparent", color: theme.inkDim,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontWeight: 500, fontSize: 12,
  padding: "8px 16px", borderRadius: 999, cursor: "pointer",
};
