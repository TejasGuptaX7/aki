"use client"

import { useState, useEffect, useCallback } from "react"
import { Save } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface OrgSettings {
  name: string
  hermes_model: string
  idle_minutes: number
  spend_cap_hard: number
  spend_cap_soft: number
  data_retention_days: number
}

export default function AdminSettings() {
  const { authedFetch } = useAuthToken()
  const [settings, setSettings] = useState<OrgSettings>({
    name: "",
    hermes_model: "gpt-4",
    idle_minutes: 30,
    spend_cap_hard: 1000,
    spend_cap_soft: 500,
    data_retention_days: 90,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const fetchSettings = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/admin/org")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSettings({
        name: data.name || "",
        hermes_model: data.hermes_model || "gpt-4",
        idle_minutes: data.idle_minutes || 30,
        spend_cap_hard: data.spend_cap_hard || 1000,
        spend_cap_soft: data.spend_cap_soft || 500,
        data_retention_days: data.data_retention_days || 90,
      })
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load settings")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchSettings()
  }, [fetchSettings])

  const saveSettings = async () => {
    setSaving(true)
    setSuccess(false)
    try {
      const res = await authedFetch("/v1/admin/org", {
        method: "PATCH",
        body: JSON.stringify(settings),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save settings")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  const fields: { key: keyof OrgSettings; label: string; type: string }[] = [
    { key: "name", label: "Organization Name", type: "text" },
    { key: "hermes_model", label: "Hermes Model", type: "text" },
    { key: "idle_minutes", label: "Idle Minutes", type: "number" },
    { key: "spend_cap_hard", label: "Spend Cap (Hard)", type: "number" },
    { key: "spend_cap_soft", label: "Spend Cap (Soft)", type: "number" },
    { key: "data_retention_days", label: "Data Retention (Days)", type: "number" },
  ]

  return (
    <div>
      <SectionHeader kicker="ORGANIZATION" title="Settings" subtitle="Configure your organization's AI platform settings" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchSettings} /></div>}

      {success && (
        <div
          style={{
            background: theme.accentDim,
            border: "1px solid rgba(197,236,79,0.3)",
            borderRadius: 8,
            padding: "12px 16px",
            fontFamily: theme.body,
            fontSize: 14,
            color: theme.accent,
            marginBottom: 16,
          }}
        >
          Settings saved successfully.
        </div>
      )}

      <div
        style={{
          background: theme.bgSoft,
          border: "1px solid " + theme.hair,
          borderRadius: 8,
          padding: 24,
          maxWidth: 600,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {fields.map((field) => (
            <div key={field.key}>
              <label
                style={{
                  fontFamily: theme.mono,
                  fontSize: 11,
                  textTransform: "uppercase",
                  letterSpacing: "0.22em",
                  color: theme.inkFaint,
                  display: "block",
                  marginBottom: 6,
                }}
              >
                {field.label}
              </label>
              <input
                type={field.type}
                value={settings[field.key]}
                onChange={(e) =>
                  setSettings((prev) => ({
                    ...prev,
                    [field.key]: field.type === "number" ? Number(e.target.value) : e.target.value,
                  }))
                }
                style={{
                  width: "100%",
                  height: 40,
                  background: theme.bg,
                  border: "1px solid " + theme.hair,
                  borderRadius: 8,
                  color: theme.ink,
                  padding: "0 14px",
                  fontFamily: theme.body,
                  fontSize: 14,
                  outline: "none",
                }}
                onFocus={(e) => { e.target.style.borderColor = theme.accent }}
                onBlur={(e) => { e.target.style.borderColor = theme.hair }}
              />
            </div>
          ))}
        </div>

        <button
          onClick={saveSettings}
          disabled={saving}
          style={{
            marginTop: 24,
            background: theme.accent,
            color: theme.bg,
            border: "none",
            borderRadius: 999,
            padding: "10px 24px",
            fontFamily: theme.body,
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
            opacity: saving ? 0.6 : 1,
          }}
        >
          <Save size={14} />
          {saving ? "Saving..." : "Save Settings"}
        </button>
      </div>
    </div>
  )
}
