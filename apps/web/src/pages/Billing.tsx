"use client"

import { useState, useEffect, useCallback } from "react"
import { DollarSign, MessageSquare, Briefcase, Wrench } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface BillingData {
  total_cost: number
  chats: number
  jobs: number
  tool_calls: number
  daily: DailyEntry[]
}

interface DailyEntry {
  date: string
  cost: number
  chats: number
  jobs: number
  tool_calls: number
}

export default function Billing() {
  const { authedFetch } = useAuthToken()
  const [data, setData] = useState<BillingData | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const fetchBilling = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/billing/usage?days=30")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const d = await res.json()
      setData(d)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load billing data")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchBilling()
  }, [fetchBilling])

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  const summary = data
    ? [
        { label: "Total Cost", value: `$${data.total_cost.toFixed(2)}`, icon: DollarSign },
        { label: "Chats", value: data.chats.toLocaleString(), icon: MessageSquare },
        { label: "Jobs", value: data.jobs.toLocaleString(), icon: Briefcase },
        { label: "Tool Calls", value: data.tool_calls.toLocaleString(), icon: Wrench },
      ]
    : []

  return (
    <div>
      <SectionHeader kicker="BILLING" title="Usage" subtitle="Your usage and cost breakdown for the last 30 days" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchBilling} /></div>}

      {/* Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginBottom: 32 }}>
        {summary.map((s) => {
          const Icon = s.icon
          return (
            <div key={s.label} style={{ background: theme.bgSoft, border: "1px solid " + theme.hair, borderRadius: 8, padding: 20 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <Icon size={16} color={theme.inkFaint} />
                <span style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint }}>
                  {s.label}
                </span>
              </div>
              <div style={{ fontFamily: theme.display, fontSize: 28, color: theme.ink }}>
                {s.value}
              </div>
            </div>
          )
        })}
      </div>

      {/* Daily Breakdown */}
      <div style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, marginBottom: 12 }}>
        Daily Breakdown
      </div>
      {(!data?.daily || data.daily.length === 0) ? (
        <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, padding: 16 }}>No billing data available.</div>
      ) : (
        <div style={{ background: theme.bgSoft, border: "1px solid " + theme.hair, borderRadius: 8, overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 100px 80px 80px 100px",
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
            <span>Date</span>
            <span style={{ textAlign: "right" }}>Cost</span>
            <span style={{ textAlign: "right" }}>Chats</span>
            <span style={{ textAlign: "right" }}>Jobs</span>
            <span style={{ textAlign: "right" }}>Tool Calls</span>
          </div>
          {data.daily.map((day) => (
            <div
              key={day.date}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px 80px 80px 100px",
                gap: 8,
                padding: "10px 16px",
                borderBottom: "1px solid " + theme.hair,
                fontFamily: theme.body,
                fontSize: 13,
                color: theme.ink,
                alignItems: "center",
              }}
            >
              <span style={{ color: theme.inkDim }}>{new Date(day.date).toLocaleDateString()}</span>
              <span style={{ textAlign: "right", fontFamily: theme.mono, fontSize: 12 }}>${day.cost.toFixed(4)}</span>
              <span style={{ textAlign: "right", fontFamily: theme.mono, fontSize: 12 }}>{day.chats}</span>
              <span style={{ textAlign: "right", fontFamily: theme.mono, fontSize: 12 }}>{day.jobs}</span>
              <span style={{ textAlign: "right", fontFamily: theme.mono, fontSize: 12 }}>{day.tool_calls}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
