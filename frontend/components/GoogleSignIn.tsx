"use client";

import { supabase } from "@/lib/supabase";
import { useState } from "react";
import { MetalFx } from "metal-fx";
import { useMounted } from "@/lib/useMounted";

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
  // Transparent fill means the waves/grid show through — the shadow keeps the label readable over bright bars.
  textShadow: "0 1px 3px rgba(0,0,0,0.9), 0 0 10px rgba(0,0,0,0.8)",
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

export default function GoogleSignIn() {
  const [open, setOpen] = useState(false);
  const mounted = useMounted();

  const signIn = () =>
    // redirectTo must be listed in Supabase Auth > URL Configuration > Redirect URLs — otherwise Supabase falls back to the Site URL and /auth/callback never exchanges the code.
    supabase?.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${location.origin}/auth/callback` },
    });

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

  // MetalFx renders differently on the server (no WebGL) and in the browser; add the ring
  // only after hydration so the server HTML matches the first client render.
  return mounted ? (
    <MetalFx preset="silver" variant="button" innerShadow>
      {button}
    </MetalFx>
  ) : (
    button
  );
}
