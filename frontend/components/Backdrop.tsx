"use client";

import { usePathname } from "next/navigation";
import Background from "@/components/Background";

/** The ONE Auris backdrop, mounted from the root layout so it survives landing -> dashboard navigation — per-page backdrops remounted the grid and flashed a cut. Only the landing page ("/") draws the waves. */
export default function Backdrop() {
  return <Background waves={usePathname() === "/"} />;
}
