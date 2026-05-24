"use client"

import { useState, useEffect, useCallback } from "react"
import { useNavigate } from "react-router"
import { Plus, Clock, DollarSign } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"
import StatusBadge from "@/components/StatusBadge"

interface Job {
  id: string
  brief: string
  status: "queued" | "running" | "done" | "failed" | "cancelled"
  created_at: string
  cost: number | null
}

export default function Jobs() {
  const { authedFetch } = useAuthToken()
  const navigate = useNavigate()
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [brief, setBrief] = useState("")
  const [cron, setCron] = useState("")
  const [creating, setCreating] = useState(false)

  const fetchJobs = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/jobs")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setJobs(data || [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load jobs")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchJobs()
  }, [fetchJobs])

  // Poll every 5s when jobs are running
  useEffect(() => {
    const hasRunning = jobs.some((j) => j.status === "queued" || j.status === "running")
    if (!hasRunning) return
    const interval = setInterval(fetchJobs, 5000)
    return () => clearInterval(interval)
  }, [jobs, fetchJobs])

  const createJob = async () => {
    if (!brief.trim()) return
    setCreating(true)
    try {
      const res = await authedFetch("/v1/jobs", {
        method: "POST",
        body: JSON.stringify({
          brief: brief.trim(),
          ...(cron.trim() ? { cron: cron.trim() } : {}),
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setModalOpen(false)
      setBrief("")
      setCron("")
      fetchJobs()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create job")
    } finally {
      setCreating(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <SectionHeader kicker="ASYNC TASKS" title="Jobs" subtitle="Manage and monitor asynchronous AI agent tasks" />
        <button
          onClick={() => setModalOpen(true)}
          style={{
            background: theme.accent,
            color: theme.bg,
            border: "none",
            borderRadius: 999,
            padding: "8px 20px",
            fontFamily: theme.body,
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Plus size={14} />
          New Job
        </button>
      </div>

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchJobs} /></div>}

      {jobs.length === 0 && (
        <div
          style={{
            background: theme.bgSoft,
            border: "1px solid " + theme.hair,
            borderRadius: 8,
            padding: 48,
            textAlign: "center",
          }}
        >
          <BriefcaseIcon size={32} color={theme.inkFaint} />
          <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, marginTop: 12 }}>
            No jobs yet. Create your first job to get started.
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {jobs.map((job) => (
          <div
            key={job.id}
            onClick={() => navigate(`/jobs/${job.id}`)}
            style={{
              background: theme.bgSoft,
              border: "1px solid " + theme.hair,
              borderRadius: 8,
              padding: "16px 20px",
              cursor: "pointer",
              transition: "border-color 0.15s ease",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(241,237,224,0.2)" }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = theme.hair }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
              <div
                style={{
                  fontFamily: theme.body,
                  fontSize: 14,
                  color: theme.ink,
                  lineHeight: 1.4,
                  flex: 1,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  marginRight: 12,
                }}
              >
                {job.brief}
              </div>
              <StatusBadge status={job.status} />
            </div>
            <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
              <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, display: "flex", alignItems: "center", gap: 4 }}>
                <Clock size={10} />
                {new Date(job.created_at).toLocaleString()}
              </span>
              {job.cost !== null && (
                <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, display: "flex", alignItems: "center", gap: 4 }}>
                  <DollarSign size={10} />
                  ${job.cost.toFixed(4)}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Create Modal */}
      {modalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 200,
          }}
          onClick={() => setModalOpen(false)}
        >
          <div
            style={{
              background: theme.bgSoft,
              border: "1px solid " + theme.hair,
              borderRadius: 12,
              padding: 32,
              width: 480,
              maxWidth: "90vw",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ fontFamily: theme.display, fontSize: 20, color: theme.ink, margin: "0 0 20px" }}>
              New Job
            </h3>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, display: "block", marginBottom: 6 }}>
                Brief
              </label>
              <textarea
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                placeholder="Describe what the AI agent should do..."
                style={{
                  width: "100%",
                  minHeight: 100,
                  background: theme.bg,
                  border: "1px solid " + theme.hair,
                  borderRadius: 8,
                  color: theme.ink,
                  padding: "10px 14px",
                  fontFamily: theme.body,
                  fontSize: 14,
                  resize: "vertical",
                  outline: "none",
                }}
                onFocus={(e) => { e.target.style.borderColor = theme.accent }}
                onBlur={(e) => { e.target.style.borderColor = theme.hair }}
              />
            </div>
            <div style={{ marginBottom: 20 }}>
              <label style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, display: "block", marginBottom: 6 }}>
                Cron Schedule (optional)
              </label>
              <input
                type="text"
                value={cron}
                onChange={(e) => setCron(e.target.value)}
                placeholder="e.g. 0 9 * * *"
                style={{
                  width: "100%",
                  height: 40,
                  background: theme.bg,
                  border: "1px solid " + theme.hair,
                  borderRadius: 8,
                  color: theme.ink,
                  padding: "0 14px",
                  fontFamily: theme.mono,
                  fontSize: 13,
                  outline: "none",
                }}
                onFocus={(e) => { e.target.style.borderColor = theme.accent }}
                onBlur={(e) => { e.target.style.borderColor = theme.hair }}
              />
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                onClick={() => setModalOpen(false)}
                style={{
                  background: "transparent",
                  color: theme.ink,
                  border: "1px solid " + theme.hair,
                  borderRadius: 999,
                  padding: "8px 18px",
                  fontFamily: theme.body,
                  fontSize: 14,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={createJob}
                disabled={creating || !brief.trim()}
                style={{
                  background: theme.accent,
                  color: theme.bg,
                  border: "none",
                  borderRadius: 999,
                  padding: "8px 20px",
                  fontFamily: theme.body,
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: brief.trim() ? "pointer" : "not-allowed",
                  opacity: brief.trim() ? 1 : 0.4,
                }}
              >
                {creating ? "Creating..." : "Create Job"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function BriefcaseIcon({ size, color }: { size: number; color: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
      <path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2" />
    </svg>
  )
}
