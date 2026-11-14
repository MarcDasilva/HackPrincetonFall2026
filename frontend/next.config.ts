import path from "node:path";
import type { NextConfig } from "next";

// The FastAPI backend (backend/README.md runs it on :8000). Proxied under /api so the browser
// talks to one origin and no CORS setup is needed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // A stray package-lock.json higher up (e.g. in the home folder) makes Next guess the wrong
  // workspace root; pin it to this folder.
  turbopack: { root: path.join(__dirname) },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
