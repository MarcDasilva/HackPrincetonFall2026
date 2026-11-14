import MetalTitle from "@/components/MetalTitle";
import GoogleSignIn from "@/components/GoogleSignIn";

/** The splash title, subtitle and sign-in button. data-landing-hero is the handle the post-login outro (components/GoogleSignIn.tsx) fades — rename BOTH or the hero stays visible. */
export default function LandingHero({ fontFamily }: { fontFamily: string }) {
  return (
    <div data-landing-hero style={{ width: "100%", height: "100vh", position: "relative" }}>
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
        <MetalTitle fontFamily={fontFamily} />
        <p
          style={{
            fontFamily,
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
        <div style={{ display: "flex", justifyContent: "center", fontFamily, marginTop: 14, pointerEvents: "auto" }}>
          <GoogleSignIn />
        </div>
      </div>
    </div>
  );
}
