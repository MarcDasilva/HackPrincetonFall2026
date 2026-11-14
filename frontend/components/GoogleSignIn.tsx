"use client";

import { supabase } from "@/lib/supabase";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import gsap from "gsap";
import { useMounted } from "./useMounted";
import { MetalFx } from "@/components/metal";

const buttonStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  height: 68,
  minWidth: 68,
  // (68 - 34px logo) / 2 keeps the logo dead-centre while collapsed.
  padding: "0 17px",
  border: 0,
  borderRadius: 999,
  background: "transparent",
  color: "#ffffff",
  font: "inherit",
  fontSize: "clamp(16px, 1.5vw, 22px)",
  letterSpacing: "0.06em",
  textTransform: "lowercase",
};

const GoogleG = () => (
  <svg width="34" height="34" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
    <path fill="#FBBC05" d="M10.5 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.9-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l7.9-6.1z" />
    <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
  </svg>
);

const clearPopupFlag = () => {
  document.cookie = "auris_popup=; path=/; max-age=0";
};

export default function GoogleSignIn() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const leaving = useRef(false);
  const mounted = useMounted();

  // Google sign-in runs in a POPUP so this page never reloads: a full-page OAuth redirect lands on a cold page that must rebuild the title, waves and every WebGL ring from scratch — that rebuild is the lag and the jagged intro. Here the landing page stays warm, plays the outro, then navigates client-side. app/auth/callback/route.ts owns the popup's other half (the postMessage).
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== location.origin || e.data !== "auris-signed-in" || leaving.current) return;
      leaving.current = true;
      router.prefetch("/dashboard");
      // Hero fades while the waves slide off the bottom; the dashboard's own intro takes over from the bare grid.
      gsap
        .timeline({ onComplete: () => router.push("/dashboard") })
        .to("[data-landing-hero]", { opacity: 0, duration: 0.7, ease: "power1.in" })
        .to("[data-landing-waves]", { yPercent: 100, duration: 1.3, ease: "power2.in" }, 0.2);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [router]);

  const signIn = async () => {
    if (!supabase) return;
    // redirectTo must be listed in Supabase Auth > URL Configuration > Redirect URLs — otherwise Supabase falls back to the Site URL and /auth/callback never exchanges the code.
    const redirectTo = `${location.origin}/auth/callback`;
    // Open synchronously inside the click or the browser blocks it; the URL is filled in once Supabase returns it.
    const popup = window.open("", "auris-login", "width=500,height=650");
    if (!popup) {
      // Popup blocked: fall back to the full-page redirect (plain dashboard intro, no outro).
      clearPopupFlag();
      supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo } });
      return;
    }
    document.cookie = "auris_popup=1; path=/; max-age=300; samesite=lax";
    const { data, error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo, skipBrowserRedirect: true } });
    if (error || !data.url) {
      popup.close();
      clearPopupFlag();
      return;
    }
    popup.location.href = data.url;
    // A popup closed without finishing must not leave the flag behind — a later full-page login would hit the popup branch.
    const watch = setInterval(() => {
      if (popup.closed) {
        clearInterval(watch);
        clearPopupFlag();
      }
    }, 500);
  };

  // The button has no fill so the grid shows through; the metal ring is the only chrome.
  // The ring mounts after hydration (see useMounted); until then the same button renders bare, so nothing shifts.
  const button = (
    <button
      type="button"
      aria-label="Sign in with Google"
      onClick={signIn}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      disabled={!supabase}
      title={supabase ? "Sign in with Google" : "Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in .env.local"}
      style={{ ...buttonStyle, cursor: supabase ? "pointer" : "not-allowed", opacity: supabase ? 1 : 0.6 }}
    >
      <GoogleG />
      {/* Width animates via max-width — auto widths can't transition. MetalFx re-measures through its ResizeObserver, so the ring follows the slide. */}
      <span
        aria-hidden="true"
        style={{
          overflow: "hidden",
          whiteSpace: "nowrap",
          maxWidth: open ? 120 : 0,
          marginLeft: open ? 14 : 0,
          opacity: open ? 1 : 0,
          transition: "max-width 0.8s ease, margin-left 0.8s ease, opacity 0.6s ease",
        }}
      >
        sign in
      </span>
    </button>
  );
  return mounted ? (
    <MetalFx preset="silver" variant="button" innerShadow normalizeHostStyles={false}>
      {button}
    </MetalFx>
  ) : (
    button
  );
}
