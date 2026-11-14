"use client";

import { MetalText, PRESETS } from "metal-fx";
import { useMounted } from "@/lib/useMounted";

// metal-fx exposes no speed prop; the shader clock multiplies by preset.speed on every frame, so lowering it on the shared PRESETS slows ALL metal (title and button ring) — raise to speed up.
const METAL_SPEED = 0.12;
for (const preset of Object.values(PRESETS)) {
  preset.modes.dark.speed = METAL_SPEED;
  preset.modes.light.speed = METAL_SPEED;
}

// font-size is in vw so the word scales with the viewport like the old 45%-wide SVG did; ~18vw of Gambarino "Auris" is an eyeballed match — change the number to resize.
export default function MetalTitle({ fontFamily }: { fontFamily: string }) {
  // MetalText renders a fallback on the server (no WebGL) and a canvas in the browser, so
  // render plain text until hydration finishes, then swap in the metal effect.
  const mounted = useMounted();
  const font = `400 18vw/1 ${fontFamily}`;
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "flex-end",
        filter: "drop-shadow(0 6px 10px rgba(0,0,0,0.7)) drop-shadow(0 12px 40px rgba(0,0,0,0.8))",
      }}
    >
      {mounted ? (
        <MetalText font={font} color="#fff" strength={1}>
          Auris
        </MetalText>
      ) : (
        <span style={{ font, color: "#fff" }}>Auris</span>
      )}
    </div>
  );
}
