"use client"

import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router"
import { Users, DollarSign, Building2, Plug, Settings, Shield, BarChart3, Trash2 } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface AuditSummary {
  total_users: number
  total_cost_30d: number
  active_departments: number
  total_connections: number
}

export default function Admin() {
  const navigate = useNavigate()
  const { authedFetch } = useAuthToken()
  const [summary, setSummary] = useState<AuditSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const fetchSummary = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/admin/audit-summary")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSummary(data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load summary")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchSummary()
  }, [fetchSummary])

  const stats = summary
    ? [
        { label: "Total Users", value: summary.total_users.toLocaleString(), icon: Users },
        { label: "Cost (30d)", value: `$${summary.total_cost_30d.toFixed(2)}`, icon: DollarSign },
        { label: "Departments", value: summary.active_departments.toLocaleString(), icon: Building2 },
        { label: "Connections", value: summary.total_connections.toLocaleString(), icon: Plug },
      ]
    : []

  const navCards = [
    { label: "Settings", path: "/admin/settings", icon: Settings, desc: "Organization configuration" },
    { label: "Users", path: "/admin/users", icon: Users, desc: "Manage team members" },
    { label: "Departments", path: "/admin/departments", icon: Building2, desc: "Department management" },
    { label: "Usage", path: "/admin/usage", icon: BarChart3, desc: "Usage analytics" },
    { label: "GDPR", path: "/admin/gdpr", icon: Trash2, desc: "Data export & deletion" },
  ]

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  return (
    <div>
      <SectionHeader kicker="ADMINISTRATION" title="Dashboard" subtitle="Organization overview and management" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchSummary} /></div>}

      {/* Stats Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16, marginBottom: 32 }}>
        {stats.map((stat) => {
          const Icon = stat.icon
          return (
            <div
              key={stat.label}
              style={{
                background: theme.bgSoft,
                border: "1px solid " + theme.hair,
                borderRadius: 8,
                padding: 20,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <Icon size={16} color={theme.inkFaint} />
                <span style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint }}>
                  {stat.label}
                </span>
              </div>
              <div style={{ fontFamily: theme.display, fontSize: 28, color: theme.ink }}>
                {stat.value}
              </div>
            </div>
          )
        })}
      </div>

      {/* Navigation Cards */}
      <div
        style={{
          fontFamily: theme.mono,
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.22em",
          color: theme.inkFaint,
          marginBottom: 12,
        }}
      >
        Management
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
        {navCards.map((card) => {
          const Icon = card.icon
          return (
            <div
              key={card.path}
              onClick={() => navigate(card.path)}
              style={{
                background: theme.bgSoft,
                border: "1px solid " + theme.hair,
                borderRadius: 8,
                padding: 20,
                cursor: "pointer",
                transition: "border-color 0.15s ease",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(241,237,224,0.2)" }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = theme.hair }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <Icon size={18} color={theme.accent} />
                <span style={{ fontFamily: theme.body, fontSize: 15, fontWeight: 500, color: theme.ink }}>
                  {card.label}
                </span>
              </div>
              <div style={{ fontFamily: theme.body, fontSize: 13, color: theme.inkDim }}>
                {card.desc}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
