"use client"

import { useState } from "react"
import { Download, Trash2, AlertTriangle } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

export default function AdminGDPR() {
  const { authedFetch } = useAuthToken()
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleExport = async () => {
    setExporting(true)
    setErr(null)
    try {
      const res = await authedFetch("/v1/gdpr/export")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `aki-export-${new Date().toISOString().split("T")[0]}.ndjson`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Export failed")
    } finally {
      setExporting(false)
    }
  }

  const handleDelete = async () => {
    const confirmed = window.confirm(
      "WARNING: This will permanently delete all your data from the platform. This action cannot be undone. Are you sure?"
    )
    if (!confirmed) return

    setDeleting(true)
    setErr(null)
    try {
      const res = await authedFetch("/v1/gdpr/delete", { method: "POST" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      alert("Your data deletion request has been submitted. It may take up to 30 days to complete.")
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete request failed")
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div>
      <SectionHeader kicker="PRIVACY" title="GDPR" subtitle="Data export and account deletion" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={() => setErr(null)} /></div>}

      {/* Export */}
      <div
        style={{
          background: theme.bgSoft,
          border: "1px solid " + theme.hair,
          borderRadius: 8,
          padding: 24,
          marginBottom: 24,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <Download size={18} color={theme.accent} />
          <h3 style={{ fontFamily: theme.body, fontSize: 16, fontWeight: 500, color: theme.ink, margin: 0 }}>
            Export Your Data
          </h3>
        </div>
        <p style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, lineHeight: 1.5, marginBottom: 16 }}>
          Download a complete copy of all your data in NDJSON format. This includes chat history, jobs, connections, and settings.
        </p>
        <button
          onClick={handleExport}
          disabled={exporting}
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
            opacity: exporting ? 0.6 : 1,
          }}
        >
          <Download size={14} />
          {exporting ? "Exporting..." : "Export Data"}
        </button>
      </div>

      {/* Danger Zone */}
      <div
        style={{
          background: "rgba(239,68,68,0.06)",
          border: "1px solid rgba(239,68,68,0.2)",
          borderRadius: 8,
          padding: 24,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <AlertTriangle size={18} color="#ef4444" />
          <h3 style={{ fontFamily: theme.body, fontSize: 16, fontWeight: 500, color: "#ef4444", margin: 0 }}>
            Delete Account
          </h3>
        </div>
        <p style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, lineHeight: 1.5, marginBottom: 16 }}>
          Permanently delete all your data from the Aki platform. This includes all chats, jobs, brain memories, and connections. This action cannot be undone.
        </p>
        <button
          onClick={handleDelete}
          disabled={deleting}
          style={{
            background: "rgba(239,68,68,0.12)",
            color: "#ef4444",
            border: "1px solid rgba(239,68,68,0.3)",
            borderRadius: 999,
            padding: "8px 20px",
            fontFamily: theme.body,
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            opacity: deleting ? 0.6 : 1,
          }}
        >
          <Trash2 size={14} />
          {deleting ? "Processing..." : "Delete Account"}
        </button>
      </div>
    </div>
  )
}
