"use client"

import { useAuth as useClerkAuth } from "@clerk/clerk-react"
import { useCallback } from "react"
import { API_URL } from "@/theme"

export function useAuthToken() {
  const { getToken, isLoaded, isSignedIn } = useClerkAuth()

  const authedFetch = useCallback(
    async (path: string, init?: RequestInit) => {
      const token = await getToken({ template: "aki" })
      return fetch(`${API_URL}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...init?.headers,
        },
      })
    },
    [getToken]
  )

  return { getToken, authedFetch, isLoaded, isSignedIn }
}
