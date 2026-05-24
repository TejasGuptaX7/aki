"use client"

import { useState, useEffect, useCallback } from "react"
import { ClipboardList, Hash, ChevronDown, ChevronRight } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface AuditEvent {
  id: string
  timestamp: string
  actor: string
  action: string
  target: string
  payload: Record<string, unknown>
  content_hash: string
  prev_hash: string
}

export default function Audit() {
  const { authedFetch } = useAuthToken()
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const fetchEvents = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/audit?limit=100")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setEvents(data.events || [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load audit log")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  const totalEvents = events.length
  const todayEvents = events.filter((e) => {
    const d = new Date(e.timestamp)
    const now = new Date()
    return d.toDateString() === now.toDateString()
  }).length

  const actionCounts: Record<string, number> = {}
  events.forEach((e) => {
    actionCounts[e.action] = (actionCounts[e.action] || 0) + 1
  })
  const topActions = Object.entries(actionCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  return (
    <div>
      <SectionHeader kicker="ACTIVITY LOG" title="Audit" subtitle="Immutable audit trail of all platform activity" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchEvents} /></div>}

      {/* Summary Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginBottom: 24 }}>
        {[
          { label: "Total Events", value: totalEvents.toLocaleString() },
          { label: "Events Today", value: todayEvents.toLocaleString() },
          ...(topActions.length > 0 ? [{ label: "Top Action", value: `${topActions[0][0]} (${topActions[0][1]})` }] : []),
        ].map((stat) => (
          <div
            key={stat.label}
            style={{
              background: theme.bgSoft,
              border: "1px solid " + theme.hair,
              borderRadius: 8,
              padding: 16,
            }}
          >
            <div style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, marginBottom: 6 }}>
              {stat.label}
            </div>
            <div style={{ fontFamily: theme.display, fontSize: 24, color: theme.ink }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* Table */}
      <div style={{ background: theme.bgSoft, border: "1px solid " + theme.hair, borderRadius: 8, overflow: "hidden" }}>
        {/* Header */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "180px 140px 100px 1fr 36px",
            gap: 8,
            padding: "10px 16px",
            background: theme.hairSoft,
            fontFamily: theme.mono,
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: theme.inkDim,
            borderBottom: "1px solid " + theme.hair,
          }}
        >
          <span>Timestamp</span>
          <span>Actor</span>
          <span>Action</span>
          <span>Target</span>
          <span></span>
        </div>

        {events.length === 0 && (
          <div style={{ padding: 32, textAlign: "center", fontFamily: theme.body, fontSize: 14, color: theme.inkDim }}>
            <ClipboardList size={28} color={theme.inkFaint} style={{ marginBottom: 8, display: "block", margin: "0 auto 8px" }} />
            No audit events yet.
          </div>
        )}

        {events.map((evt) => (
          <div key={evt.id} style={{ borderBottom: "1px solid " + theme.hair }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "180px 140px 100px 1fr 36px",
                gap: 8,
                padding: "12px 16px",
                alignItems: "center",
                cursor: "pointer",
              }}
              onClick={() => setExpandedId(expandedId === evt.id ? null : evt.id)}
            >
              <span style={{ fontFamily: theme.mono, fontSize: 12, color: theme.inkDim }}>
                {new Date(evt.timestamp).toLocaleString()}
              </span>
              <span style={{ fontFamily: theme.body, fontSize: 13, color: theme.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {evt.actor}
              </span>
              <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.accent, textTransform: "uppercase" }}>
                {evt.action}
              </span>
              <span style={{ fontFamily: theme.body, fontSize: 13, color: theme.inkDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {evt.target}
              </span>
              <span style={{ display: "flex", justifyContent: "center" }}>
                {expandedId === evt.id ? <ChevronDown size={14} color={theme.inkFaint} /> : <ChevronRight size={14} color={theme.inkFaint} />}
              </span>
            </div>

            {expandedId === evt.id && (
              <div style={{ padding: "0 16px 16px", background: "rgba(241,237,224,0.02)" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 10 }}>
                  <div>
                    <div style={{ fontFamily: theme.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, marginBottom: 4, display: "flex", alignItems: "center", gap: 4 }}>
                      <Hash size={10} />
                      Content Hash
                    </div>
                    <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, wordBreak: "break-all" }}>
                      {evt.content_hash}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontFamily: theme.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, marginBottom: 4, display: "flex", alignItems: "center", gap: 4 }}>
                      <Hash size={10} />
                      Prev Hash
                    </div>
                    <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkDim, wordBreak: "break-all" }}>
                      {evt.prev_hash}
                    </div>
                  </div>
                </div>
                <pre
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 11,
                    color: theme.inkDim,
                    background: theme.bg,
                    border: "1px solid " + theme.hair,
                    borderRadius: 4,
                    padding: 10,
                    margin: 0,
                    overflow: "auto",
                    maxHeight: 200,
                  }}
                >
                  {JSON.stringify(evt.payload, null, 2)}
                </pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
