"use client"

import { useState, useEffect, useCallback } from "react"
import { Building2, Plus, UserPlus, X } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface Department {
  id: string
  name: string
  slug: string
  model: string
  idle_minutes: number
  slack_channel: string | null
}

export default function AdminDepartments() {
  const { authedFetch } = useAuthToken()
  const [departments, setDepartments] = useState<Department[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [addMemberOpen, setAddMemberOpen] = useState(false)
  const [selectedDeptId, setSelectedDeptId] = useState<string | null>(null)

  // Create form
  const [name, setName] = useState("")
  const [slug, setSlug] = useState("")
  const [model, setModel] = useState("gpt-4")
  const [slackChannel, setSlackChannel] = useState("")
  const [creating, setCreating] = useState(false)

  // Add member form
  const [memberUserId, setMemberUserId] = useState("")
  const [memberRole, setMemberRole] = useState<"owner" | "admin" | "member" | "viewer">("member")
  const [addingMember, setAddingMember] = useState(false)

  const fetchDepartments = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/departments")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDepartments(data || [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load departments")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchDepartments()
  }, [fetchDepartments])

  // Auto-generate slug from name
  useEffect(() => {
    setSlug(name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""))
  }, [name])

  const createDepartment = async () => {
    if (!name.trim() || !slug.trim()) return
    setCreating(true)
    try {
      const res = await authedFetch("/v1/departments", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          slug: slug.trim(),
          model: model.trim(),
          slack_channel: slackChannel.trim() || null,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setCreateOpen(false)
      setName("")
      setSlug("")
      setModel("gpt-4")
      setSlackChannel("")
      fetchDepartments()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create department")
    } finally {
      setCreating(false)
    }
  }

  const addMember = async () => {
    if (!selectedDeptId || !memberUserId.trim()) return
    setAddingMember(true)
    try {
      const res = await authedFetch(`/v1/departments/${selectedDeptId}/members`, {
        method: "POST",
        body: JSON.stringify({
          clerk_user_id: memberUserId.trim(),
          role: memberRole,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setAddMemberOpen(false)
      setMemberUserId("")
      setMemberRole("member")
      setSelectedDeptId(null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to add member")
    } finally {
      setAddingMember(false)
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
        <SectionHeader kicker="ORG STRUCTURE" title="Departments" subtitle="Manage departments and their AI configurations" />
        <button
          onClick={() => setCreateOpen(true)}
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
          Create Department
        </button>
      </div>

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchDepartments} /></div>}

      {departments.length === 0 && (
        <div
          style={{
            background: theme.bgSoft,
            border: "1px solid " + theme.hair,
            borderRadius: 8,
            padding: 48,
            textAlign: "center",
          }}
        >
          <Building2 size={32} color={theme.inkFaint} />
          <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, marginTop: 12 }}>
            No departments yet. Create your first department.
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {departments.map((dept) => (
          <div
            key={dept.id}
            style={{
              background: theme.bgSoft,
              border: "1px solid " + theme.hair,
              borderRadius: 8,
              padding: "16px 20px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <Building2 size={16} color={theme.inkDim} />
                <span style={{ fontFamily: theme.body, fontSize: 15, fontWeight: 500, color: theme.ink }}>
                  {dept.name}
                </span>
                <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint }}>
                  {dept.slug}
                </span>
              </div>
              <button
                onClick={() => { setSelectedDeptId(dept.id); setAddMemberOpen(true) }}
                style={{
                  background: "transparent",
                  border: "1px solid " + theme.hair,
                  color: theme.inkDim,
                  borderRadius: 999,
                  padding: "4px 12px",
                  fontFamily: theme.body,
                  fontSize: 12,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <UserPlus size={12} />
                Add Member
              </button>
            </div>
            <div style={{ display: "flex", gap: 20, fontFamily: theme.mono, fontSize: 12, color: theme.inkDim }}>
              <span>Model: {dept.model}</span>
              <span>Idle: {dept.idle_minutes}m</span>
              {dept.slack_channel && <span>Slack: {dept.slack_channel}</span>}
            </div>
          </div>
        ))}
      </div>

      {/* Create Modal */}
      {createOpen && (
        <ModalOverlay onClose={() => setCreateOpen(false)}>
          <h3 style={{ fontFamily: theme.display, fontSize: 20, color: theme.ink, margin: "0 0 20px" }}>
            Create Department
          </h3>
          <FormField label="Name" value={name} onChange={setName} />
          <FormField label="Slug" value={slug} onChange={setSlug} mono />
          <FormField label="Model" value={model} onChange={setModel} />
          <FormField label="Slack Channel (optional)" value={slackChannel} onChange={setSlackChannel} />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 8 }}>
            <GhostButton onClick={() => setCreateOpen(false)}>Cancel</GhostButton>
            <PrimaryButton onClick={createDepartment} disabled={creating || !name.trim() || !slug.trim()}>
              {creating ? "Creating..." : "Create"}
            </PrimaryButton>
          </div>
        </ModalOverlay>
      )}

      {/* Add Member Modal */}
      {addMemberOpen && (
        <ModalOverlay onClose={() => setAddMemberOpen(false)}>
          <h3 style={{ fontFamily: theme.display, fontSize: 20, color: theme.ink, margin: "0 0 20px" }}>
            Add Member
          </h3>
          <FormField label="User ID" value={memberUserId} onChange={setMemberUserId} mono />
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, display: "block", marginBottom: 6 }}>
              Role
            </label>
            <select
              value={memberRole}
              onChange={(e) => setMemberRole(e.target.value as typeof memberRole)}
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
            >
              <option value="owner">Owner</option>
              <option value="admin">Admin</option>
              <option value="member">Member</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 8 }}>
            <GhostButton onClick={() => setAddMemberOpen(false)}>Cancel</GhostButton>
            <PrimaryButton onClick={addMember} disabled={addingMember || !memberUserId.trim()}>
              {addingMember ? "Adding..." : "Add Member"}
            </PrimaryButton>
          </div>
        </ModalOverlay>
      )}
    </div>
  )
}

function ModalOverlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
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
      onClick={onClose}
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
        {children}
      </div>
    </div>
  )
}

function FormField({ label, value, onChange, mono }: { label: string; value: string; onChange: (v: string) => void; mono?: boolean }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.inkFaint, display: "block", marginBottom: 6 }}>
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: "100%",
          height: 40,
          background: theme.bg,
          border: "1px solid " + theme.hair,
          borderRadius: 8,
          color: theme.ink,
          padding: "0 14px",
          fontFamily: mono ? theme.mono : theme.body,
          fontSize: 14,
          outline: "none",
        }}
        onFocus={(e) => { e.target.style.borderColor = theme.accent }}
        onBlur={(e) => { e.target.style.borderColor = theme.hair }}
      />
    </div>
  )
}

function GhostButton({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
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
      {children}
    </button>
  )
}

function PrimaryButton({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: theme.accent,
        color: theme.bg,
        border: "none",
        borderRadius: 999,
        padding: "8px 20px",
        fontFamily: theme.body,
        fontSize: 14,
        fontWeight: 500,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
      }}
    >
      {children}
    </button>
  )
}
