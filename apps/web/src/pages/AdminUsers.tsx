"use client"

import { useState, useEffect, useCallback } from "react"
import { Users } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface OrgUser {
  clerk_user_id: string
  email: string
  role: "owner" | "admin" | "member" | "viewer"
  created_at: string
}

const roleStyles: Record<string, React.CSSProperties> = {
  owner: { background: theme.accentDim, color: theme.accent, border: "1px solid rgba(197,236,79,0.3)" },
  admin: { background: "rgba(59,130,246,0.12)", color: "#3b82f6", border: "1px solid rgba(59,130,246,0.3)" },
  member: { background: "rgba(241,237,224,0.06)", color: theme.inkDim, border: "1px solid " + theme.hair },
  viewer: { background: "transparent", color: theme.inkFaint, border: "1px solid " + theme.hair },
}

export default function AdminUsers() {
  const { authedFetch } = useAuthToken()
  const [users, setUsers] = useState<OrgUser[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const fetchUsers = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/admin/users")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setUsers(data.users || [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load users")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
        <div style={{ width: 24, height: 24, border: "2px solid " + theme.hair, borderTopColor: theme.accent, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    )
  }

  return (
    <div>
      <SectionHeader kicker="TEAM" title="Users" subtitle="Manage organization members and roles" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchUsers} /></div>}

      {users.length === 0 && (
        <div
          style={{
            background: theme.bgSoft,
            border: "1px solid " + theme.hair,
            borderRadius: 8,
            padding: 48,
            textAlign: "center",
          }}
        >
          <Users size={32} color={theme.inkFaint} />
          <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, marginTop: 12 }}>
            No users found.
          </div>
        </div>
      )}

      {users.length > 0 && (
        <div style={{ background: theme.bgSoft, border: "1px solid " + theme.hair, borderRadius: 8, overflow: "hidden" }}>
          {/* Header */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 100px 160px",
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
            <span>User ID</span>
            <span>Email</span>
            <span>Role</span>
            <span>Joined</span>
          </div>

          {users.map((u) => (
            <div
              key={u.clerk_user_id}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 100px 160px",
                gap: 8,
                padding: "12px 16px",
                borderBottom: "1px solid " + theme.hair,
                alignItems: "center",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(241,237,224,0.03)" }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent" }}
            >
              <span
                style={{
                  fontFamily: theme.mono,
                  fontSize: 12,
                  color: theme.inkDim,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={u.clerk_user_id}
              >
                {u.clerk_user_id}
              </span>
              <span style={{ fontFamily: theme.body, fontSize: 13, color: theme.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {u.email}
              </span>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 999,
                  padding: "2px 10px",
                  fontFamily: theme.mono,
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  width: "fit-content",
                  ...roleStyles[u.role],
                }}
              >
                {u.role}
              </span>
              <span style={{ fontFamily: theme.mono, fontSize: 12, color: theme.inkDim }}>
                {new Date(u.created_at).toLocaleDateString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
