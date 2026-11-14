"use client";

import { MetalText } from "@/components/metal";
import { useMounted } from "./useMounted";

// Borderless wordmark: the metal text alone, no tile or ring. Sized by eye against the dock icons (76px tall, app/dashboard/Dashboard.tsx) — raise to enlarge.
const SIZE = 48;

/** Fades the wordmark in ONLY when the page was reached by client-side navigation (the landing outro's router.push after sign-in). A refresh or direct load — including the popup-blocked full-page OAuth redirect — makes this path the document's own first URL, so it shows instantly. */
const fadeOnClientNav = (el: HTMLSpanElement | null) => {
  const first = performance.getEntriesByType("navigation")[0]?.name;
  if (el && first && new URL(first).pathname !== location.pathname) el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 900, easing: "ease-out" });
};

export default function AurisLogo({ fontFamily }: { fontFamily: string }) {
  if (!useMounted()) return <span style={{ display: "inline-block", height: SIZE }} />;
  return (
    <span ref={fadeOnClientNav} data-testid="auris-logo" style={{ display: "inline-block" }}>
      <MetalText font={`400 ${SIZE}px/1 ${fontFamily}`} color="#fff" strength={1}>
        Auris
      </MetalText>
    </span>
  );
}
