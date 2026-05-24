"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { useParams, useNavigate } from "react-router"
import { ArrowLeft, Clock, DollarSign, XCircle } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import ErrorBanner from "@/components/ErrorBanner"
import StatusBadge from "@/components/StatusBadge"

interface Job {
  id: string
  brief: string
  status: "queued" | "running" | "done" | "failed" | "cancelled"
  created_at: string
  cost: number | null
  result?: string
}

interface JobEvent {
  id: string
  timestamp: string
  kind: string
  payload: Record<string, unknown>
}

export default function JobDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { authedFetch } = useAuthToken()
  const [job, setJob] = useState<Job | null>(null)
  const [events, setEvents] = useState<JobEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  const fetchJob = useCallback(async () => {
    if (!id) return
    try {
      setErr(null)
      const res = await authedFetch(`/v1/jobs/${id}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setJob(data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load job")
    } finally {
      setLoading(false)
    }
  }, [id, authedFetch])

  const fetchEvents = useCallback(async () => {
    if (!id) return
    try {
      const res = await authedFetch(`/v1/jobs/${id}/events`)
      if (!res.ok) return
      const data = await res.json()
      setEvents(data.events || [])
    } catch {
      // silently fail
    }
  }, [id, authedFetch])

  useEffect(() => {
    fetchJob()
    fetchEvents()
  }, [fetchJob, fetchEvents])

  // SSE for live events when job is running
  useEffect(() => {
    if (!id || !job || (job.status !== "running" && job.status !== "queued")) return

    const token = authedFetch
    let es: EventSource | null = null

    const connect = async () => {
      try {
        const t = await (await authedFetch("")).json().catch(() => null)
        // We can't set headers on EventSource, so we use a different approach
        // Poll events instead for the authed endpoint
      } catch {
        // fallback to polling
      }
    }

    // Use polling fallback since EventSource doesn't support custom headers easily
    const interval = setInterval(() => {
      fetchEvents()
      fetchJob()
    }, 3000)

    return () => clearInterval(interval)
  }, [id, job?.status, fetchEvents, fetchJob])

  const cancelJob = async () => {
    if (!id || !job || (job.status !== "running" && job.status !== "queued")) return
    setCancelling(true)
    try {
      const res = await authedFetch(`/v1/jobs/${id}/cancel`, { method: "POST" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      fetchJob()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to cancel job")
    } finally {
      setCancelling(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  if (!job) {
    return <ErrorBanner message="Job not found" onRetry={fetchJob} />
  }

  return (
    <div>
      <button
        onClick={() => navigate("/jobs")}
        style={{
          background: "transparent",
          border: "none",
          color: theme.inkDim,
          fontFamily: theme.body,
          fontSize: 14,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 6,
          marginBottom: 24,
        }}
      >
        <ArrowLeft size={16} />
        Back to Jobs
      </button>

      <div
        style={{
          background: theme.bgSoft,
          border: "1px solid " + theme.hair,
          borderRadius: 8,
          padding: 24,
          marginBottom: 24,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
          <h1 style={{ fontFamily: theme.display, fontSize: 24, color: theme.ink, margin: 0, lineHeight: 1.3 }}>
            {job.brief}
          </h1>
          <StatusBadge status={job.status} />
        </div>

        <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
          <span style={{ fontFamily: theme.mono, fontSize: 12, color: theme.inkDim, display: "flex", alignItems: "center", gap: 4 }}>
            <Clock size={12} />
            {new Date(job.created_at).toLocaleString()}
          </span>
          {job.cost !== null && (
            <span style={{ fontFamily: theme.mono, fontSize: 12, color: theme.inkDim, display: "flex", alignItems: "center", gap: 4 }}>
              <DollarSign size={12} />
              ${job.cost.toFixed(4)}
            </span>
          )}
        </div>

        {(job.status === "running" || job.status === "queued") && (
          <button
            onClick={cancelJob}
            disabled={cancelling}
            style={{
              background: "rgba(239,68,68,0.12)",
              color: "#ef4444",
              border: "1px solid rgba(239,68,68,0.3)",
              borderRadius: 999,
              padding: "6px 16px",
              fontFamily: theme.body,
              fontSize: 13,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <XCircle size={14} />
            {cancelling ? "Cancelling..." : "Cancel Job"}
          </button>
        )}

        {job.result && (
          <div
            style={{
              marginTop: 16,
              padding: 16,
              background: theme.bg,
              border: "1px solid " + theme.hair,
              borderRadius: 8,
              fontFamily: theme.body,
              fontSize: 14,
              color: theme.ink,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
            }}
          >
            <div style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, marginBottom: 8 }}>
              Result
            </div>
            {job.result}
          </div>
        )}
      </div>

      {/* Events Timeline */}
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
        Event Timeline
      </div>

      {events.length === 0 && (
        <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, padding: "16px 0" }}>
          No events yet.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {events.map((evt) => (
          <div
            key={evt.id}
            style={{
              background: theme.bgSoft,
              border: "1px solid " + theme.hair,
              borderRadius: 8,
              padding: 12,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.accent, textTransform: "uppercase" }}>
                {evt.kind}
              </span>
              <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint }}>
                {new Date(evt.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <pre
              style={{
                fontFamily: theme.mono,
                fontSize: 11,
                color: theme.inkDim,
                margin: 0,
                overflow: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {JSON.stringify(evt.payload, null, 2)}
            </pre>
          </div>
        ))}
      </div>
    </div>
  )
}
