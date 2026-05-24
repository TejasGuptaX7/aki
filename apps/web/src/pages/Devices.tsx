"use client"

import { useState, useEffect, useCallback } from "react"
import { Monitor, Plus, Trash2, Clock } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface Device {
  id: string
  name: string
  last_seen: string
  created_at: string
}

interface PairCode {
  code: string
  expires_at: string
}

export default function Devices() {
  const { authedFetch } = useAuthToken()
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [pairCode, setPairCode] = useState<PairCode | null>(null)
  const [generating, setGenerating] = useState(false)
  const [countdown, setCountdown] = useState(0)

  const fetchDevices = useCallback(async () => {
    try {
      setErr(null)
      const res = await authedFetch("/v1/devices")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDevices(data || [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load devices")
    } finally {
      setLoading(false)
    }
  }, [authedFetch])

  useEffect(() => {
    fetchDevices()
  }, [fetchDevices])

  // Poll for new devices every 5s
  useEffect(() => {
    const interval = setInterval(fetchDevices, 5000)
    return () => clearInterval(interval)
  }, [fetchDevices])

  // Countdown timer
  useEffect(() => {
    if (!pairCode) return
    const expires = new Date(pairCode.expires_at).getTime()
    const update = () => {
      const remaining = Math.max(0, Math.floor((expires - Date.now()) / 1000))
      setCountdown(remaining)
      if (remaining <= 0) setPairCode(null)
    }
    update()
    const interval = setInterval(update, 1000)
    return () => clearInterval(interval)
  }, [pairCode])

  const generatePairCode = async () => {
    setGenerating(true)
    try {
      const res = await authedFetch("/v1/devices/pair/start", { method: "POST" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setPairCode({ code: data.code, expires_at: data.expires_at })
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to generate pair code")
    } finally {
      setGenerating(false)
    }
  }

  const revokeDevice = async (deviceId: string) => {
    try {
      const res = await authedFetch(`/v1/devices/${deviceId}/revoke`, { method: "POST" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      fetchDevices()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to revoke device")
    }
  }

  const formatTimeRemaining = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, "0")}`
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
        <SectionHeader kicker="DESKTOP CLIENTS" title="Devices" subtitle="Manage Aki Desktop connections" />
        <button
          onClick={generatePairCode}
          disabled={generating}
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
            opacity: generating ? 0.6 : 1,
          }}
        >
          <Plus size={14} />
          Generate Pair Code
        </button>
      </div>

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={fetchDevices} /></div>}

      {pairCode && (
        <div
          style={{
            background: theme.accentDim,
            border: "1px solid rgba(197,236,79,0.3)",
            borderRadius: 8,
            padding: 24,
            marginBottom: 24,
            textAlign: "center",
          }}
        >
          <div style={{ fontFamily: theme.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.22em", color: theme.accent, marginBottom: 12 }}>
            Pair Code
          </div>
          <div style={{ fontFamily: theme.mono, fontSize: 48, fontWeight: 700, color: theme.accent, letterSpacing: "0.15em", marginBottom: 8 }}>
            {pairCode.code}
          </div>
          <div style={{ fontFamily: theme.mono, fontSize: 13, color: theme.inkDim, display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
            <Clock size={12} />
            Expires in {formatTimeRemaining(countdown)}
          </div>
        </div>
      )}

      {devices.length === 0 && !pairCode && (
        <div
          style={{
            background: theme.bgSoft,
            border: "1px solid " + theme.hair,
            borderRadius: 8,
            padding: 48,
            textAlign: "center",
          }}
        >
          <Monitor size={32} color={theme.inkFaint} />
          <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, marginTop: 12 }}>
            No devices paired. Generate a pair code to connect your first device.
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {devices.map((device) => (
          <div
            key={device.id}
            style={{
              background: theme.bgSoft,
              border: "1px solid " + theme.hair,
              borderRadius: 8,
              padding: "14px 20px",
              display: "flex",
              alignItems: "center",
              gap: 14,
            }}
          >
            <Monitor size={18} color={theme.inkDim} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.ink, fontWeight: 500 }}>
                {device.name}
              </div>
              <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint, marginTop: 2 }}>
                Last seen: {new Date(device.last_seen).toLocaleString()}
              </div>
            </div>
            <button
              onClick={() => revokeDevice(device.id)}
              style={{
                background: "transparent",
                border: "1px solid rgba(239,68,68,0.3)",
                color: "#ef4444",
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
              <Trash2 size={12} />
              Revoke
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
