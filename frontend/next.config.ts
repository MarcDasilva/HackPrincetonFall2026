import path from "node:path";

import type { NextConfig } from "next";

// The FastAPI backend (backend/README.md runs it on :8000). Proxied under /api so the browser
// talks to one origin and no CORS setup is needed.
// Defaults to the SAME backend the rest of the app calls (NEXT_PUBLIC_API_URL, lib/run.ts) — a different one serves no /api/sim or none of this app's patients.
const BACKEND_URL = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  // A stray package-lock.json higher up (e.g. in the home folder) makes Next guess the wrong
  // workspace root; pin it to this folder.
  turbopack: { root: path.join(__dirname) },
  partialPrefetching: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
