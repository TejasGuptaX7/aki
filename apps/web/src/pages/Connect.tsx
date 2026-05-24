"use client"

import { useState, useEffect, useCallback } from "react"
import { Mail, Calendar, FileText, Trello, Slack, Github, Globe, ToggleLeft, ToggleRight } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"
import StatusBadge from "@/components/StatusBadge"

interface Connection {
  id: string
  provider: string
  status: "pending" | "active" | "disabled"
  connected_at: string
}

const providers = [
  { key: "gmail", name: "Gmail", icon: Mail },
  { key: "google_calendar", name: "Google Calendar", icon: Calendar },
  { key: "google_docs", name: "Google Docs", icon: FileText },
  { key: "notion", name: "Notion", icon: Trello },
  { key: "slack", name: "Slack", icon: Slack },
  { key: "github", name: "GitHub", icon: Github },
  { key: "browser", name: "Browser Use", icon: Globe },
]

export default function Connect() {
  const { authedFetch } = useAuthToken()
  const [connections, setConnections] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [browserEnabled, setBrowserEnabled] = useState(false)

  const fetchConnections = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/connections")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setConnections(data || [])
      const browserConn = (data || []).find((c: Connection) => c.provider === "browser")
      setBrowserEnabled(browserConn?.status === "active")
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load connections")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchConnections()
  }, [fetchConnections])

  const startOAuth = async (provider: string) => {
    try {
      const res = await authedFetch(`/connections/oauth/start?provider=${provider}`, { method: "POST" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.url) {
        window.location.href = data.url
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "OAuth failed")
    }
  }

  const toggleBrowser = async () => {
    try {
      const endpoint = browserEnabled ? "/connections/browser/disable" : "/connections/browser/enable"
      const res = await authedFetch(endpoint, { method: "POST" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setBrowserEnabled(!browserEnabled)
      fetchConnections()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to toggle browser")
    }
  }

  const getConnection = (key: string) => connections.find((c) => c.provider === key)

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  return (
    <div>
      <SectionHeader kicker="INTEGRATIONS" title="Connect" subtitle="Link your SaaS tools and services" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchConnections} /></div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
        {providers.map((provider) => {
          const conn = getConnection(provider.key)
          const Icon = provider.icon
          const isBrowser = provider.key === "browser"

          return (
            <div
              key={provider.key}
              style={{
                background: theme.bgSoft,
                border: "1px solid " + theme.hair,
                borderRadius: 8,
                padding: 20,
                display: "flex",
                flexDirection: "column",
                gap: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <Icon size={20} color={theme.inkDim} />
                  <span style={{ fontFamily: theme.body, fontSize: 15, fontWeight: 500, color: theme.ink }}>
                    {provider.name}
                  </span>
                </div>
                <StatusBadge
                  status={conn?.status || "disabled"}
                  label={conn?.status || "disconnected"}
                />
              </div>

              {conn?.connected_at && (
                <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint }}>
                  Connected {new Date(conn.connected_at).toLocaleDateString()}
                </div>
              )}

              <div style={{ marginTop: "auto", paddingTop: 8 }}>
                {isBrowser ? (
                  <button
                    onClick={toggleBrowser}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: theme.inkDim,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: 0,
                      fontFamily: theme.body,
                      fontSize: 14,
                    }}
                  >
                    {browserEnabled ? <ToggleRight size={32} color={theme.accent} /> : <ToggleLeft size={32} color={theme.inkFaint} />}
                    {browserEnabled ? "Enabled" : "Disabled"}
                  </button>
                ) : (
                  <button
                    onClick={() => startOAuth(provider.key)}
                    style={{
                      background: conn?.status === "active" ? "transparent" : theme.accent,
                      color: conn?.status === "active" ? theme.inkDim : theme.bg,
                      border: conn?.status === "active" ? "1px solid " + theme.hair : "none",
                      borderRadius: 999,
                      padding: "6px 16px",
                      fontFamily: theme.body,
                      fontSize: 13,
                      cursor: "pointer",
                      width: "100%",
                    }}
                  >
                    {conn?.status === "active" ? "Disconnect" : "Connect"}
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
