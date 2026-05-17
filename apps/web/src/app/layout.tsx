import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Source_Serif_4, Geist, JetBrains_Mono } from "next/font/google";
import { AgentsProvider } from "@/lib/agents";
import "./globals.css";

const sourceSerif = Source_Serif_4({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
});

const geist = Geist({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
});

export const metadata: Metadata = {
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_SITE_URL ?? "https://aki.dev",
  ),
  title: {
    default: "Aki — named agents your team can DM in Slack",
    template: "%s",
  },
  description:
    "Spin up named agents your team can DM in Slack. Each one runs the work, cites its sources, and asks before anything irreversible. Free during beta.",
  keywords: [
    "AI agents", "Slack bot", "autonomous agents", "AI for teams",
    "AI assistant", "AI coworker", "agent workspace",
  ],
  openGraph: {
    type: "website",
    siteName: "Aki",
    title: "Aki — named agents your team can DM in Slack",
    description:
      "Spin up named agents your team can DM in Slack. Each one runs the work, cites its sources, and asks before anything irreversible.",
    // TODO(founder): supply /public/og-default.png (1200x630). For now Next
    // will skip og:image rather than render a broken preview.
  },
  twitter: {
    card: "summary_large_image",
    title: "Aki — named agents your team can DM in Slack",
    description:
      "Spin up named agents your team can DM in Slack. Free during beta.",
  },
  icons: {
    // Reuses the existing /apps/web/src/app/favicon.ico shipped with the
    // scaffold. Founder should replace with a brand favicon eventually.
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider>
      <html
        lang="en"
        className={`${sourceSerif.variable} ${geist.variable} ${jetbrainsMono.variable} h-full antialiased`}
      >
        <body className="min-h-full">
          <AgentsProvider>{children}</AgentsProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
