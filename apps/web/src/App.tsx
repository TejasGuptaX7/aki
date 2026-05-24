import { Routes, Route, Navigate } from "react-router"
import { useAuth } from "@clerk/clerk-react"
import AppShell from "@/components/AppShell"
import Login from "@/pages/Login"
import Chat from "@/pages/Chat"
import Jobs from "@/pages/Jobs"
import JobDetail from "@/pages/JobDetail"
import Connect from "@/pages/Connect"
import Devices from "@/pages/Devices"
import Audit from "@/pages/Audit"
import Brain from "@/pages/Brain"
import Admin from "@/pages/Admin"
import AdminSettings from "@/pages/AdminSettings"
import AdminUsers from "@/pages/AdminUsers"
import AdminDepartments from "@/pages/AdminDepartments"
import AdminUsage from "@/pages/AdminUsage"
import AdminGDPR from "@/pages/AdminGDPR"
import Billing from "@/pages/Billing"
import Me from "@/pages/Me"

function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth()

  if (!isLoaded) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#15161a",
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            border: "2px solid rgba(241,237,224,0.12)",
            borderTopColor: "#c5ec4f",
            borderRadius: "50%",
            animation: "spin 0.8s linear infinite",
          }}
        />
      </div>
    )
  }

  if (!isSignedIn) {
    return <Navigate to="/login" replace />
  }

  return <AppShell>{children}</AppShell>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/chat"
        element={
          <ProtectedLayout>
            <Chat />
          </ProtectedLayout>
        }
      />
      <Route
        path="/jobs"
        element={
          <ProtectedLayout>
            <Jobs />
          </ProtectedLayout>
        }
      />
      <Route
        path="/jobs/:id"
        element={
          <ProtectedLayout>
            <JobDetail />
          </ProtectedLayout>
        }
      />
      <Route
        path="/connect"
        element={
          <ProtectedLayout>
            <Connect />
          </ProtectedLayout>
        }
      />
      <Route
        path="/devices"
        element={
          <ProtectedLayout>
            <Devices />
          </ProtectedLayout>
        }
      />
      <Route
        path="/audit"
        element={
          <ProtectedLayout>
            <Audit />
          </ProtectedLayout>
        }
      />
      <Route
        path="/brain"
        element={
          <ProtectedLayout>
            <Brain />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin"
        element={
          <ProtectedLayout>
            <Admin />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin/settings"
        element={
          <ProtectedLayout>
            <AdminSettings />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin/users"
        element={
          <ProtectedLayout>
            <AdminUsers />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin/departments"
        element={
          <ProtectedLayout>
            <AdminDepartments />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin/usage"
        element={
          <ProtectedLayout>
            <AdminUsage />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin/gdpr"
        element={
          <ProtectedLayout>
            <AdminGDPR />
          </ProtectedLayout>
        }
      />
      <Route
        path="/billing"
        element={
          <ProtectedLayout>
            <Billing />
          </ProtectedLayout>
        }
      />
      <Route
        path="/me"
        element={
          <ProtectedLayout>
            <Me />
          </ProtectedLayout>
        }
      />
      <Route path="/" element={<Navigate to="/chat" replace />} />
      <Route path="*" element={<Navigate to="/chat" replace />} />
    </Routes>
  )
}
