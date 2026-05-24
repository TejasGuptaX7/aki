"use client"

import { SignIn } from "@clerk/clerk-react"
import { theme } from "@/theme"

export default function Login() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: theme.bg,
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div
          style={{
            fontFamily: theme.display,
            fontStyle: "italic",
            fontSize: 32,
            color: theme.ink,
            marginBottom: 32,
          }}
        >
          Aki
        </div>
        <SignIn
          routing="path"
          path="/login"
          signUpUrl="/sign-up"
          afterSignInUrl="/chat"
          appearance={{
            elements: {
              card: {
                background: theme.bgSoft,
                border: "1px solid " + theme.hair,
                boxShadow: "none",
              },
              headerTitle: {
                fontFamily: theme.display,
                color: theme.ink,
              },
              headerSubtitle: {
                fontFamily: theme.body,
                color: theme.inkDim,
              },
              socialButtonsBlockButton: {
                border: "1px solid " + theme.hair,
                color: theme.ink,
              },
              formFieldLabel: {
                fontFamily: theme.body,
                color: theme.inkDim,
              },
              formFieldInput: {
                background: theme.bg,
                border: "1px solid " + theme.hair,
                color: theme.ink,
              },
              formButtonPrimary: {
                background: theme.accent,
                color: theme.bg,
                fontFamily: theme.body,
                borderRadius: 999,
              },
              footerActionLink: {
                color: theme.accent,
              },
              dividerLine: {
                background: theme.hair,
              },
              dividerText: {
                fontFamily: theme.mono,
                color: theme.inkFaint,
              },
              identityPreviewText: {
                color: theme.ink,
              },
              alertText: {
                color: theme.ink,
              },
            },
          }}
        />
      </div>
    </div>
  )
}
