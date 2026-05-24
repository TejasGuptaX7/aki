"use client"

import { useState, useEffect, useCallback } from "react"
import { User, Building2, Shield } from "lucide-react"
import { useUser } from "@clerk/clerk-react"
import { useNavigate } from "react-router"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface ProfileData {
  user: {
    id: string
    email: string
    first_name: string
    last_name: string
    role: string
  }
  org: {
    id: string
    name: string
  }
}

export default function Me() {
  const { user: clerkUser } = useUser()
  const navigate = useNavigate()
  const { authedFetch } = useAuthToken()
  const [profile, setProfile] = useState<ProfileData | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const fetchProfile = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/me")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setProfile(data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load profile")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchProfile()
  }, [fetchProfile])

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  return (
    <div>
      <SectionHeader kicker="ACCOUNT" title="Profile" subtitle="Your user information and organization details" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchProfile} /></div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* User Card */}
        <div style={{ background: theme.bgSoft, border: "1px solid " + theme.hair, borderRadius: 8, padding: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
            <User size={18} color={theme.accent} />
            <span style={{ fontFamily: theme.body, fontSize: 16, fontWeight: 500, color: theme.ink }}>
              User Information
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="Name" value={`${clerkUser?.firstName || ""} ${clerkUser?.lastName || ""}`.trim() || profile?.user?.first_name + " " + profile?.user?.last_name || "N/A"} />
            <Field label="Email" value={clerkUser?.emailAddresses?.[0]?.emailAddress || profile?.user?.email || "N/A"} />
            <Field label="User ID" value={clerkUser?.id || profile?.user?.id || "N/A"} mono />
            <Field label="Role" value={profile?.user?.role || "Member"} />
          </div>
        </div>

        {/* Org Card */}
        <div style={{ background: theme.bgSoft, border: "1px solid " + theme.hair, borderRadius: 8, padding: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
            <Building2 size={18} color={theme.accent} />
            <span style={{ fontFamily: theme.body, fontSize: 16, fontWeight: 500, color: theme.ink }}>
              Organization
            </span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label="Name" value={profile?.org?.name || "N/A"} />
            <Field label="Org ID" value={profile?.org?.id || "N/A"} mono />
          </div>

          <button
            onClick={() => navigate("/admin")}
            style={{
              marginTop: 20,
              background: "transparent",
              border: "1px solid " + theme.hair,
              color: theme.inkDim,
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
            <Shield size={14} />
            Go to Admin
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontFamily: theme.mono, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontFamily: mono ? theme.mono : theme.body, fontSize: 14, color: theme.ink, wordBreak: "break-word" }}>
        {value}
      </div>
    </div>
  )
}
