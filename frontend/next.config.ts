import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // A stray package-lock.json higher up (e.g. in the home folder) makes Next guess the wrong
  // workspace root; pin it to this folder.
  turbopack: { root: path.join(__dirname) },
};

export default nextConfig;
