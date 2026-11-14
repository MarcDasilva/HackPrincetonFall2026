import ShapeGrid from "@/components/ShapeGrid";
import SlicedWaves from "@/components/SlicedWaves";

/** ONE source for the Auris backdrop — the splash and the dashboard both render this, so they cannot drift apart. Fixed so it stays put while the dashboard scrolls. */
export default function Background() {
  return (
    <div style={{ position: "fixed", inset: 0, background: "#000", pointerEvents: "none" }}>
      {/* mouseInteraction off: pointer never lights cells; clickCascade off: clicks do nothing */}
      <ShapeGrid
        shape="square"
        direction="diagonal"
        lineColor="#2a2734"
        hoverColor="#ffffff"
        hoverFillColor="#ffffff"
        fillOpacity={0.15}
        cellSize={40}
        speed={0.5}
        tiltX={0}
        tiltY={0}
        rainbow={false}
        lineWidth={1}
        radius={0}
        trail={0.6}
        glow={0.35}
        twinkle={0}
        fade={0.4}
        clickCascade={false}
        mouseInteraction={false}
        intro={false}
      />
      <div style={{ position: "absolute", inset: 0 }}>
        <SlicedWaves
          color1="#10b981"
          color2="#ff5fa2"
          color3="#5b8cff"
          ribbons={4}
          spacing={24}
          perspective={0}
          blur={0.6}
          glow={1}
          position={0.88}
          mouseInteraction={false}
          barWidth={0.4}
          ribbonHeight={0.22}
          spread={0.1}
          amplitude={0.095}
          frequency={1.15}
          curve={0.35}
          slices={0}
          speed={1}
          brightness={1.35}
          rotation={0}
          grain={0.08}
          fade={0}
          opacity={1}
          intro
          lightMode={false}
        />
      </div>
    </div>
  );
}
