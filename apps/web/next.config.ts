import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin Turbopack root to this app — otherwise Next walks up and picks the
  // stray /Users/tejasgupta/package-lock.json instead of apps/web.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
