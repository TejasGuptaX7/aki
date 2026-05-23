"use client";

import * as React from "react";
import { useAuth } from "@clerk/nextjs";
import { theme, API_URL } from "@/lib/theme";
import { AppShell, ErrorBanner, SectionHeader } from "@/components/AppShell";

type Department = {
  id: string;
  name: string;
  slug: string;
  hermes_model_name: string | null;
  hermes_idle_minutes: number;
  created_at: string;
};

export default function DepartmentsAdmin() {
  const { getToken } = useAuth();
  const [departments, setDepartments] = React.useState<Department[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState(false);
  const [showNew, setShowNew] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/departments`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error(`departments ${r.status}: ${await r.text()}`);
      setDepartments(await r.json());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [getToken]);

  React.useEffect(() => { refresh(); }, [refresh]);

  async function create(name: string, slug: string, model: string) {
    setCreating(true);
    setErr(null);
    try {
      const token = await getToken({ template: "aki" });
      const r = await fetch(`${API_URL}/v1/departments`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name, slug,
          hermes_model_name: model || undefined,
          hermes_idle_minutes: 15,
        }),
      });
      if (!r.ok) throw new Error(`create ${r.status}: ${await r.text()}`);
      setShowNew(false);
      refresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <AppShell>
      <SectionHeader
        kicker="admin · departments"
        title={<>One Hermes runtime <span style={{ fontStyle: "italic", fontWeight: 500, color: theme.inkDim }}>per department.</span></>}
        lede="Departments shard your Hermes containers and scope which connectors each agent can use."
      />
      <div style={{ padding: "32px 56px" }}>
        {err && <ErrorBanner>{err}</ErrorBanner>}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.18em", textTransform: "uppercase" }}>
            {departments.length} dept{departments.length === 1 ? "" : "s"}
          </span>
          <button onClick={() => setShowNew(true)} style={{
            background: theme.accent, color: theme.bg, border: "none",
            fontFamily: theme.body, fontWeight: 600, fontSize: 14,
            padding: "10px 22px", borderRadius: 999, cursor: "pointer",
          }}>
            Create department
          </button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 1, background: theme.hair }}>
          {departments.map((d) => (
            <div key={d.id} style={{
              background: theme.bg, padding: "16px 20px",
              display: "grid", gridTemplateColumns: "1fr 1fr 160px 100px", gap: 16, alignItems: "center",
            }}>
              <div>
                <div style={{ fontFamily: theme.body, fontSize: 15 }}>{d.name}</div>
                <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.16em", marginTop: 2 }}>
                  {d.slug}
                </div>
              </div>
              <div style={{ fontFamily: theme.mono, fontSize: 12, color: theme.inkDim }}>
                {d.hermes_model_name ?? <span style={{ color: theme.inkFaint }}>org default</span>}
              </div>
              <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint }}>
                idle {d.hermes_idle_minutes}m
              </div>
              <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, textAlign: "right" }}>
                {new Date(d.created_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      </div>
      {showNew && <NewDept onSubmit={create} onClose={() => setShowNew(false)} submitting={creating}/>}
    </AppShell>
  );
}

function NewDept({ onSubmit, onClose, submitting }: { onSubmit: (n: string, s: string, m: string) => void; onClose: () => void; submitting: boolean }) {
  const [name, setName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [model, setModel] = React.useState("");
  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: theme.bg, border: `1px solid ${theme.hair}`,
        padding: "32px 36px", width: 480,
      }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, letterSpacing: "0.24em", textTransform: "uppercase", marginBottom: 16 }}>
          new department
        </div>
        <input value={name} onChange={(e) => {
          setName(e.target.value);
          if (!slug) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, ""));
        }} placeholder="Name (e.g. Sales)" style={inputStyle}/>
        <div style={{ height: 12 }}/>
        <input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="slug (kebab-case)" style={inputStyle}/>
        <div style={{ height: 12 }}/>
        <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="hermes model override (optional)" style={inputStyle}/>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 20 }}>
          <button onClick={onClose} style={ghostBtn}>Cancel</button>
          <button onClick={() => onSubmit(name, slug, model)} disabled={!name.trim() || !slug.trim() || submitting} style={{
            background: theme.accent, color: theme.bg, border: "none",
            fontFamily: theme.body, fontWeight: 600, fontSize: 14,
            padding: "10px 22px", borderRadius: 999,
            opacity: !name.trim() || !slug.trim() || submitting ? 0.4 : 1,
            cursor: submitting ? "default" : "pointer",
          }}>
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box",
  background: theme.bgSoft, color: theme.ink, padding: "10px 14px",
  border: `1px solid ${theme.hair}`, borderRadius: 4,
  fontFamily: theme.body, fontSize: 14, outline: "none",
};

const ghostBtn: React.CSSProperties = {
  background: "transparent", color: theme.inkDim,
  border: `1px solid ${theme.hair}`,
  fontFamily: theme.body, fontSize: 14,
  padding: "10px 18px", borderRadius: 999, cursor: "pointer",
};
