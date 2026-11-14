import Background from "@/components/Background";
import localFont from "next/font/local";
import MetalTitle from "@/components/MetalTitle";
import GoogleSignIn from "@/components/GoogleSignIn";

const gambarino = localFont({ src: "./fonts/Gambarino-Regular.woff2" });

export default function Home() {
  return (
    <main style={{ position: "relative" }}>
      <Background />
      <div style={{ width: "100%", height: "100vh", position: "relative" }}>
        {/* Wrapper centers the title, subtitle and button as one unit. */}
        <div
          style={{
            position: "absolute",
            top: "40%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            width: "fit-content",
            pointerEvents: "none",
          }}
        >
        <MetalTitle fontFamily={gambarino.style.fontFamily} />
        <p
          style={{
            fontFamily: gambarino.style.fontFamily,
            // -1vw: -2vw would cancel the title's empty line-box space under the baseline exactly (MetalText is line-height 1); the extra 1vw is the requested breathing room.
            margin: "-1vw 0 0",
            textAlign: "center",
            color: "#fff",
            fontSize: "clamp(14px, 1.6vw, 28px)",
            letterSpacing: "0.12em",
            textTransform: "lowercase",
            textShadow: "0 2px 12px rgba(0,0,0,0.8)",
          }}
        >
          Agentic Hearing Development
        </p>
        {/* The wrapper is pointer-events none so the title never blocks the canvas; the button opts back in. */}
        <div
          style={{ display: "flex", justifyContent: "center", fontFamily: gambarino.style.fontFamily, marginTop: 14, pointerEvents: "auto" }}
        >
          <GoogleSignIn />
        </div>
        </div>
      </div>
    </main>
  );
}
