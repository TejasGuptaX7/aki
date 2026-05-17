import path from "node:path";
import createMDX from "@next/mdx";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin Turbopack root to this app — otherwise Next walks up and picks the
  // stray /Users/tejasgupta/package-lock.json instead of apps/web.
  turbopack: {
    root: path.join(__dirname),
  },
  pageExtensions: ["ts", "tsx", "mdx"],
};

const withMDX = createMDX({});

export default withMDX(nextConfig);
