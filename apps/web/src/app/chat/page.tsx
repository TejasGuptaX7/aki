"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { theme } from "@/lib/theme";
import { AppShell } from "@/components/AppShell";
import { useAgents, pickDefaultAgent } from "@/lib/agents";

/**
 * /chat is a dispatcher: send the user to their default agent's thread,
 * or to /onboarding if they don't have one yet.
 */
export default function ChatDispatcherPage() {
  const router = useRouter();
  const { agents, status, error } = useAgents();

  React.useEffect(() => {
    if (status !== "ready") return;
    const target = pickDefaultAgent(agents);
    if (!target) router.replace("/onboarding");
    else router.replace(`/chat/${target.id}`);
  }, [status, agents, router]);

  return (
    <AppShell>
      <div style={{
        padding: "48px 56px",
        fontFamily: theme.mono, fontSize: 12,
        color: error ? "#ee5959" : theme.inkFaint,
      }}>
        {error ? `failed to load agents: ${error}` : "routing to your agent…"}
      </div>
    </AppShell>
  );
}
