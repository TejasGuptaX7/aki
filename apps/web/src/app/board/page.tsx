"use client";

import * as React from "react";
import Link from "next/link";
import { theme } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";
import { useAgents, useAuthToken } from "@/lib/agents";
import { Agent, AgentBoardTile, agentsApi, ApiError } from "@/lib/api";

/**
 * Inspector Board — the post-sign-in landing surface. One tile per agent
 * with live status, currently-doing line, and a tool-call sparkline.
 *
 * Live data comes from polling /agents/board every 5s. The board endpoint
 * may 404 during a backend deploy (or pre-ship); when it does we still
 * render a tile per agent from the canonical /agents list with placeholder
 * status — that's the point of having two data sources.
 */
export default function BoardPage() {
  const { agents, status: agentsStatus, error: agentsError } = useAgents();
  const tok = useAuthToken();
  const [tiles, setTiles] = React.useState<AgentBoardTile[] | null>(null);
  const [tilesErr, setTilesErr] = React.useState<string | null>(null);
  const [boardSupported, setBoardSupported] = React.useState(true);

  React.useEffect(() => {
    let mounted = true;
    const tick = async () => {
      try {
        const data = await agentsApi.board(tok);
        if (mounted) { setTiles(data); setTilesErr(null); }
      } catch (e) {
        if (!mounted) return;
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
          setBoardSupported(false);
          setTiles([]);
          return;
        }
        setTilesErr(e instanceof Error ? e.message : String(e));
      }
    };
    tick();
    const id = setInterval(tick, 5_000);
    return () => { mounted = false; clearInterval(id); };
  }, [tok]);

  // Merge canonical agent list + board live state. Index board by id for
  // O(1) lookup; agents without a board row get a placeholder.
  const byId = React.useMemo(() => {
    const m = new Map<string, AgentBoardTile>();
    for (const t of tiles ?? []) m.set(t.id, t);
    return m;
  }, [tiles]);

  const active = agents.filter((a) => a.status === "active");
  const banner = tilesErr ?? agentsError;

  return (
    <AppShell>
      <SectionHeader
        kicker="/00 · board"
        title={<>Every agent, <em style={{ fontStyle: "italic", fontWeight: 500 }}>at a glance.</em></>}
        lede="Live status across your roster. Click any tile to drop into that agent's chat."
        right={
          <Link href="/agents" style={pillSecondary}>Manage agents</Link>
        }
      />

      {banner && <ErrorBanner>{banner}</ErrorBanner>}
      {!boardSupported && (
        <div style={{
          margin: "12px 56px 0", padding: "8px 14px",
          background: theme.bgSoft, border: `1px dashed ${theme.hair}`,
          fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
          letterSpacing: "0.18em", textTransform: "uppercase",
        }}>
          live status endpoint not yet wired · showing static roster
        </div>
      )}

      <section style={{ padding: "32px 56px 64px" }}>
        {agentsStatus === "loading" && agents.length === 0 ? (
          <TileGrid>
            {[0, 1, 2].map((i) => <SkeletonTile key={i}/>)}
          </TileGrid>
        ) : active.length === 0 ? (
          <EmptyState/>
        ) : (
          <TileGrid>
            {active.map((a) => (
              <Tile key={a.id} agent={a} live={byId.get(a.id) ?? null}/>
            ))}
          </TileGrid>
        )}
      </section>
    </AppShell>
  );
}

function TileGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="aki-board-grid" style={{
      display: "grid",
      gridTemplateColumns: "repeat(3, minmax(300px, 1fr))",
      gap: 16,
    }}>
      {children}
      <style>{`
        @media (max-width: 1240px) {
          .aki-board-grid { grid-template-columns: repeat(2, minmax(280px, 1fr)) !important; }
        }
        @media (max-width: 760px) {
          .aki-board-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

function EmptyState() {
  return (
    <div style={{
      padding: "60px 40px", background: theme.bgSoft,
      border: `1px dashed ${theme.hair}`,
      textAlign: "center", maxWidth: 560, margin: "0 auto",
    }}>
      <div style={{
        fontFamily: theme.display, fontStyle: "italic", fontWeight: 500,
        fontSize: 28, color: theme.inkLede, letterSpacing: "-0.015em", marginBottom: 14,
      }}>No agents yet.</div>
      <div style={{
        fontFamily: theme.body, fontSize: 14, color: theme.inkDim, lineHeight: 1.55,
        marginBottom: 24,
      }}>
        Spin up your first agent — three answers, two minutes — and it&rsquo;ll show up here.
      </div>
      <Link href="/onboarding" style={pillPrimary}>Spin up an agent</Link>
    </div>
  );
}

function Tile({ agent, live }: { agent: Agent; live: AgentBoardTile | null }) {
  const status = live?.status ?? "idle";
  const currentStep = live?.current_step?.trim() || "Idle";
  const sparkline = live?.sparkline ?? [];
  const startedAt = live?.started_at ?? null;
  const initials = deriveInitials(agent.name);

  return (
    <Link href={`/chat/${agent.id}`} style={{
      textDecoration: "none", color: "inherit",
      display: "flex", flexDirection: "column",
      padding: "18px 20px", minHeight: 200,
      background: theme.bgSoft, border: `1px solid ${theme.hair}`,
      borderTop: `2px solid ${statusColor(status)}`,
      transition: "border-color 0.15s ease, transform 0.15s ease",
    }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = theme.hair; e.currentTarget.style.transform = "translateY(-1px)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = theme.hair; e.currentTarget.style.transform = ""; }}
    >
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, marginBottom: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <Avatar initials={initials} accent={statusColor(status)}/>
          <div style={{ minWidth: 0 }}>
            <div style={{
              fontFamily: theme.display, fontWeight: 600, fontSize: 18,
              letterSpacing: "-0.015em", color: theme.ink,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              maxWidth: 180,
            }}>{agent.name}</div>
            <div style={{
              fontFamily: theme.mono, fontSize: 10, color: theme.inkFaint,
              letterSpacing: "0.14em",
            }}>{agent.slug}</div>
          </div>
        </div>
        <StatusPill status={status}/>
      </div>

      <div style={{
        fontFamily: theme.body, fontSize: 13, color: theme.inkLede,
        lineHeight: 1.45, marginBottom: 12,
        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        overflow: "hidden", minHeight: 38,
      }} title={currentStep}>
        {status === "idle" ? <span style={{ color: theme.inkFaint }}>Idle</span> : currentStep}
      </div>

      <ProgressBar status={status}/>

      <div style={{
        marginTop: "auto", paddingTop: 12,
        display: "flex", alignItems: "flex-end", justifyContent: "space-between",
        gap: 12,
      }}>
        <Sparkline values={sparkline}/>
        <ElapsedClock startedAt={startedAt} status={status}/>
      </div>
    </Link>
  );
}

function Avatar({ initials, accent }: { initials: string; accent: string }) {
  return (
    <div style={{
      width: 32, height: 32, borderRadius: 6,
      background: theme.bg, border: `1px solid ${accent}55`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: theme.display, fontWeight: 700, fontSize: 13,
      color: accent, flexShrink: 0,
    }}>{initials}</div>
  );
}

const STATUS_LABEL: Record<AgentBoardTile["status"], string> = {
  idle: "idle",
  thinking: "thinking",
  acting: "acting",
  waiting: "waiting on you",
  done: "done",
  errored: "errored",
};

function statusColor(status: AgentBoardTile["status"]): string {
  switch (status) {
    case "thinking": return "#e3c14f";   // warm yellow
    case "acting": return theme.accent;  // lime
    case "waiting": return "#ff9e3d";    // amber
    case "done": return "#9ec8ff";       // muted blue
    case "errored": return "#ee5959";    // red
    default: return "rgba(241,237,224,0.36)"; // idle, inkFaint
  }
}

function StatusPill({ status }: { status: AgentBoardTile["status"] }) {
  const color = statusColor(status);
  return (
    <span style={{
      fontFamily: theme.mono, fontSize: 9,
      letterSpacing: "0.18em", textTransform: "uppercase",
      color, padding: "3px 9px", borderRadius: 999,
      background: `${color}15`, border: `1px solid ${color}40`,
      whiteSpace: "nowrap", flexShrink: 0,
    }}>{STATUS_LABEL[status]}</span>
  );
}

function ProgressBar({ status }: { status: AgentBoardTile["status"] }) {
  const animate = status === "thinking" || status === "acting";
  const color = statusColor(status);
  return (
    <div style={{
      width: "100%", height: 2,
      background: "rgba(241,237,224,0.06)", overflow: "hidden",
      position: "relative",
    }}>
      {animate ? (
        <div style={{
          position: "absolute", inset: 0,
          background: `linear-gradient(90deg, transparent, ${color}, transparent)`,
          backgroundSize: "40% 100%",
          animation: "akiSlide 1.8s ease-in-out infinite",
        }}/>
      ) : (
        <div style={{
          position: "absolute", inset: 0,
          background: status === "errored" ? color : "transparent",
          opacity: status === "errored" ? 0.5 : 0,
        }}/>
      )}
      <style>{`
        @keyframes akiSlide {
          0% { background-position: -40% 0; }
          100% { background-position: 140% 0; }
        }
      `}</style>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const padded = values.length < 12
    ? [...new Array(12 - values.length).fill(0), ...values]
    : values.slice(-24);
  const max = Math.max(1, ...padded);
  const w = 110;
  const h = 24;
  const barW = w / padded.length;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-label="tool calls per minute">
      {padded.map((v, i) => {
        const barH = Math.max(1, Math.round((v / max) * h));
        const y = h - barH;
        return (
          <rect key={i}
            x={i * barW + 0.5}
            y={y}
            width={barW - 1}
            height={barH}
            fill={v > 0 ? theme.accent : "rgba(241,237,224,0.12)"}
            opacity={v > 0 ? 0.6 + 0.4 * (v / max) : 1}
          />
        );
      })}
    </svg>
  );
}

function ElapsedClock({ startedAt, status }: { startedAt: string | null; status: AgentBoardTile["status"] }) {
  const [, setTick] = React.useState(0);
  React.useEffect(() => {
    if (!startedAt) return;
    if (status === "idle" || status === "done" || status === "errored") return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [startedAt, status]);

  if (!startedAt) {
    return <span style={clockStyle(theme.inkFaint)}>--:--:--</span>;
  }
  const elapsed = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
  return <span style={clockStyle(theme.inkDim)}>{formatElapsed(elapsed)}</span>;
}

function clockStyle(color: string): React.CSSProperties {
  return {
    fontFamily: theme.mono, fontSize: 11, color,
    letterSpacing: "0.08em",
  };
}

function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function deriveInitials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[words.length - 1][0]).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}

function SkeletonTile() {
  return (
    <div style={{
      minHeight: 200, padding: "18px 20px",
      background: theme.bgSoft, border: `1px solid ${theme.hair}`,
    }}>
      <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
        <div style={{ width: 32, height: 32, background: "rgba(241,237,224,0.06)" }}/>
        <div style={{ flex: 1 }}>
          <div style={{ height: 16, width: "60%", background: "rgba(241,237,224,0.06)", marginBottom: 6 }}/>
          <div style={{ height: 10, width: "30%", background: "rgba(241,237,224,0.04)" }}/>
        </div>
      </div>
      <div style={{ height: 12, width: "85%", background: "rgba(241,237,224,0.05)", marginBottom: 8 }}/>
      <div style={{ height: 12, width: "55%", background: "rgba(241,237,224,0.05)" }}/>
    </div>
  );
}

const pillPrimary: React.CSSProperties = {
  background: theme.accent, color: theme.bg,
  fontFamily: theme.body, fontWeight: 600, fontSize: 13,
  padding: "10px 22px", borderRadius: 999, textDecoration: "none",
  display: "inline-flex", alignItems: "center",
};

const pillSecondary: React.CSSProperties = {
  background: "transparent", color: theme.inkDim,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontWeight: 500, fontSize: 13,
  padding: "9px 18px", borderRadius: 999, textDecoration: "none",
  display: "inline-flex", alignItems: "center",
};
