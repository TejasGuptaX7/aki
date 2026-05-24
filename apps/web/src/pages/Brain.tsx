"use client"

import { useState, useEffect, useCallback } from "react"
import { Search, Upload, BookOpen } from "lucide-react"
import { useAuthToken } from "@/hooks/useAuthToken"
import { theme } from "@/theme"
import SectionHeader from "@/components/SectionHeader"
import ErrorBanner from "@/components/ErrorBanner"

interface SearchResult {
  id: string
  content: string
  score: number
  source_title: string
  source_kind: string
}

interface Source {
  id: string
  title: string
  kind: string
  created_at: string
}

export default function Brain() {
  const { authedFetch } = useAuthToken()
  const [query, setQuery] = useState("")
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [ingestTitle, setIngestTitle] = useState("")
  const [ingestContent, setIngestContent] = useState("")
  const [ingesting, setIngesting] = useState(false)
  const [sources, setSources] = useState<Source[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const fetchSources = useCallback(async () => {
    try {
      const res = await authedFetch("/v1/brain/sources")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSources(data.sources || [])
    } catch {
      // silently fail for sources
    }
  }, [authedFetch])

  useEffect(() => {
    fetchSources()
  }, [fetchSources])

  const handleSearch = async () => {
    if (!query.trim()) return
    setErr(null)
    setSearching(true)
    try {
      const res = await authedFetch("/v1/brain/retrieve", {
        method: "POST",
        body: JSON.stringify({ query: query.trim(), principals: ["org_id"] }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSearchResults(data.results || [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Search failed")
    } finally {
      setSearching(false)
    }
  }

  const handleIngest = async () => {
    if (!ingestTitle.trim() || !ingestContent.trim()) return
    setErr(null)
    setSuccessMsg(null)
    setIngesting(true)
    try {
      const res = await authedFetch("/v1/brain/ingest", {
        method: "POST",
        body: JSON.stringify({
          title: ingestTitle.trim(),
          content: ingestContent.trim(),
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSuccessMsg("Content ingested successfully")
      setIngestTitle("")
      setIngestContent("")
      fetchSources()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ingest failed")
    } finally {
      setIngesting(false)
    }
  }

  return (
    <div>
      <SectionHeader kicker="KNOWLEDGE BASE" title="Brain" subtitle="Semantic search and memory ingestion for your AI agents" />

      {err && <div style={{ marginBottom: 16 }}><ErrorBanner message={err} onRetry={() => setErr(null)} /></div>}

      {successMsg && (
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
          {successMsg}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* Left: Search */}
        <div>
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
            Search Memory
          </div>
          <div style={{ display: "flex", gap: 10, marginBottom: 20 }}>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Search your knowledge base..."
              style={{
                flex: 1,
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
            <button
              onClick={handleSearch}
              disabled={searching || !query.trim()}
              style={{
                background: theme.accent,
                color: theme.bg,
                border: "none",
                borderRadius: 999,
                padding: "0 20px",
                fontFamily: theme.body,
                fontSize: 14,
                fontWeight: 500,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                opacity: searching ? 0.6 : 1,
              }}
            >
              <Search size={14} />
              {searching ? "..." : "Search"}
            </button>
          </div>

          {searchResults.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {searchResults.map((r) => (
                <div
                  key={r.id}
                  style={{
                    background: theme.bgSoft,
                    border: "1px solid " + theme.hair,
                    borderRadius: 8,
                    padding: 16,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.accent }}>
                      Score: {r.score.toFixed(3)}
                    </span>
                    <span style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint }}>
                      {r.source_kind}
                    </span>
                  </div>
                  <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.ink, lineHeight: 1.5, marginBottom: 8 }}>
                    {r.content.length > 300 ? r.content.slice(0, 300) + "..." : r.content}
                  </div>
                  <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkDim }}>
                    Source: {r.source_title}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Ingest + Sources */}
        <div>
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
            Ingest Content
          </div>
          <div
            style={{
              background: theme.bgSoft,
              border: "1px solid " + theme.hair,
              borderRadius: 8,
              padding: 20,
              marginBottom: 24,
            }}
          >
            <input
              type="text"
              value={ingestTitle}
              onChange={(e) => setIngestTitle(e.target.value)}
              placeholder="Title..."
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
                marginBottom: 10,
                outline: "none",
              }}
              onFocus={(e) => { e.target.style.borderColor = theme.accent }}
              onBlur={(e) => { e.target.style.borderColor = theme.hair }}
            />
            <textarea
              value={ingestContent}
              onChange={(e) => setIngestContent(e.target.value)}
              placeholder="Content to ingest..."
              style={{
                width: "100%",
                minHeight: 120,
                background: theme.bg,
                border: "1px solid " + theme.hair,
                borderRadius: 8,
                color: theme.ink,
                padding: "10px 14px",
                fontFamily: theme.body,
                fontSize: 14,
                resize: "vertical",
                marginBottom: 12,
                outline: "none",
              }}
              onFocus={(e) => { e.target.style.borderColor = theme.accent }}
              onBlur={(e) => { e.target.style.borderColor = theme.hair }}
            />
            <button
              onClick={handleIngest}
              disabled={ingesting || !ingestTitle.trim() || !ingestContent.trim()}
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
                opacity: ingesting ? 0.6 : 1,
              }}
            >
              <Upload size={14} />
              {ingesting ? "Ingesting..." : "Ingest"}
            </button>
          </div>

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
            Sources
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {sources.length === 0 && (
              <div style={{ fontFamily: theme.body, fontSize: 14, color: theme.inkDim, padding: "12px 0" }}>
                No sources yet. Ingest content to get started.
              </div>
            )}
            {sources.map((s) => (
              <div
                key={s.id}
                style={{
                  background: theme.bgSoft,
                  border: "1px solid " + theme.hair,
                  borderRadius: 8,
                  padding: 12,
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <BookOpen size={14} color={theme.inkFaint} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: theme.body, fontSize: 13, color: theme.ink, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {s.title}
                  </div>
                  <div style={{ fontFamily: theme.mono, fontSize: 11, color: theme.inkFaint }}>
                    {s.kind} — {new Date(s.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
