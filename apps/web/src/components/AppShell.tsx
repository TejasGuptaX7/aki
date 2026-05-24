"use client"

import { Link, useLocation } from "react-router"
import { useUser, useClerk } from "@clerk/clerk-react"
import { useState } from "react"
import {
  MessageSquare,
  Briefcase,
  Plug,
  Monitor,
  ClipboardList,
  Shield,
  ChevronDown,
  ChevronRight,
  LogOut,
} from "lucide-react"
import { theme } from "@/theme"

const mainNav = [
  { label: "Chat", path: "/chat", icon: MessageSquare },
  { label: "Jobs", path: "/jobs", icon: Briefcase },
  { label: "Connect", path: "/connect", icon: Plug },
  { label: "Devices", path: "/devices", icon: Monitor },
  { label: "Audit", path: "/audit", icon: ClipboardList },
]

const adminNav = [
  { label: "Dashboard", path: "/admin" },
  { label: "Settings", path: "/admin/settings" },
  { label: "Users", path: "/admin/users" },
  { label: "Departments", path: "/admin/departments" },
  { label: "Usage", path: "/admin/usage" },
  { label: "GDPR", path: "/admin/gdpr" },
]

function pageTitle(pathname: string): string {
  if (pathname === "/chat") return "Chat"
  if (pathname === "/jobs") return "Jobs"
  if (pathname.startsWith("/jobs/")) return "Job Detail"
  if (pathname === "/connect") return "Connections"
  if (pathname === "/devices") return "Devices"
  if (pathname === "/audit") return "Audit Log"
  if (pathname === "/brain") return "Brain"
  if (pathname === "/billing") return "Billing"
  if (pathname === "/me") return "Profile"
  if (pathname === "/admin") return "Admin Dashboard"
  if (pathname === "/admin/settings") return "Org Settings"
  if (pathname === "/admin/users") return "Users"
  if (pathname === "/admin/departments") return "Departments"
  if (pathname === "/admin/usage") return "Usage"
  if (pathname === "/admin/gdpr") return "GDPR"
  return "Aki"
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const { user } = useUser()
  const { signOut } = useClerk()
  const [adminOpen, setAdminOpen] = useState(location.pathname.startsWith("/admin"))

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      {/* Sidebar */}
      <aside
        style={{
          position: "fixed",
          left: 0,
          top: 0,
          width: 240,
          height: "100vh",
          background: theme.bgSoft,
          borderRight: "1px solid " + theme.hair,
          display: "flex",
          flexDirection: "column",
          padding: "24px 0",
          zIndex: 100,
          overflowY: "auto",
        }}
      >
        {/* Logo */}
        <Link
          to="/chat"
          style={{
            fontFamily: theme.display,
            fontStyle: "italic",
            fontSize: 24,
            color: theme.ink,
            textDecoration: "none",
            padding: "0 20px 32px",
            display: "block",
          }}
        >
          Aki
        </Link>

        {/* Main Nav */}
        <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {mainNav.map((item) => {
            const isActive = location.pathname === item.path
            const Icon = item.icon
            return (
              <Link
                key={item.path}
                to={item.path}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 20px",
                  fontFamily: theme.body,
                  fontSize: 14,
                  color: isActive ? theme.accent : theme.inkDim,
                  background: isActive ? theme.accentDim : "transparent",
                  borderLeft: isActive ? "2px solid " + theme.accent : "2px solid transparent",
                  textDecoration: "none",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.color = theme.ink
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.color = theme.inkDim
                }}
              >
                <Icon size={16} />
                {item.label}
              </Link>
            )
          })}
        </nav>

        {/* Divider */}
        <div
          style={{
            height: 1,
            background: theme.hair,
            margin: "16px 20px",
          }}
        />

        {/* Admin Nav (collapsible) */}
        <div>
          <button
            onClick={() => setAdminOpen(!adminOpen)}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              width: "100%",
              padding: "8px 20px",
              fontFamily: theme.mono,
              fontSize: 11,
              textTransform: "uppercase",
              letterSpacing: "0.22em",
              color: theme.inkFaint,
              background: "transparent",
              border: "none",
              cursor: "pointer",
            }}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Shield size={14} />
              Admin
            </span>
            {adminOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
          {adminOpen && (
            <nav style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 4 }}>
              {adminNav.map((item) => {
                const isActive = location.pathname === item.path
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    style={{
                      display: "block",
                      padding: "6px 20px 6px 44px",
                      fontFamily: theme.body,
                      fontSize: 13,
                      color: isActive ? theme.accent : theme.inkDim,
                      background: isActive ? theme.accentDim : "transparent",
                      borderLeft: isActive ? "2px solid " + theme.accent : "2px solid transparent",
                      textDecoration: "none",
                      transition: "all 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) e.currentTarget.style.color = theme.ink
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) e.currentTarget.style.color = theme.inkDim
                    }}
                  >
                    {item.label}
                  </Link>
                )
              })}
            </nav>
          )}
        </div>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* User */}
        <div
          style={{
            padding: "16px 20px",
            borderTop: "1px solid " + theme.hair,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 999,
              background: theme.accentDim,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: theme.body,
              fontSize: 12,
              fontWeight: 600,
              color: theme.accent,
              flexShrink: 0,
            }}
          >
            {user?.firstName?.[0] || user?.emailAddresses?.[0]?.emailAddress?.[0]?.toUpperCase() || "U"}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontFamily: theme.body,
                fontSize: 12,
                color: theme.ink,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {user?.firstName || user?.emailAddresses?.[0]?.emailAddress || "User"}
            </div>
          </div>
          <button
            onClick={() => signOut()}
            style={{
              background: "transparent",
              border: "none",
              color: theme.inkFaint,
              cursor: "pointer",
              padding: 4,
              display: "flex",
            }}
            title="Sign out"
          >
            <LogOut size={14} />
          </button>
        </div>
      </aside>

      {/* Main Area */}
      <div
        style={{
          marginLeft: 240,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          flex: 1,
          minWidth: 0,
        }}
      >
        {/* Top Bar */}
        <header
          style={{
            height: 56,
            borderBottom: "1px solid " + theme.hair,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 32px",
            flexShrink: 0,
          }}
        >
          <h2
            style={{
              fontFamily: theme.display,
              fontSize: 20,
              fontWeight: 400,
              color: theme.ink,
              margin: 0,
            }}
          >
            {pageTitle(location.pathname)}
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <Link
              to="/brain"
              style={{
                fontFamily: theme.mono,
                fontSize: 11,
                color: theme.inkFaint,
                textDecoration: "none",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              Brain
            </Link>
            <Link
              to="/billing"
              style={{
                fontFamily: theme.mono,
                fontSize: 11,
                color: theme.inkFaint,
                textDecoration: "none",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              Billing
            </Link>
            <Link
              to="/me"
              style={{
                fontFamily: theme.mono,
                fontSize: 11,
                color: theme.inkFaint,
                textDecoration: "none",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              Profile
            </Link>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontFamily: theme.mono,
                fontSize: 11,
                color: theme.inkDim,
              }}
            >
              <div
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: theme.accent,
                }}
              />
              Connected
            </div>
          </div>
        </header>

        {/* Content */}
        <main style={{ flex: 1, padding: "24px 32px", overflowY: "auto" }}>
          {children}
        </main>
      </div>
    </div>
  )
}
