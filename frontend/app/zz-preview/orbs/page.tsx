import Orb, { type OrbVariant } from "@/components/Orb";

const VARIANTS: OrbVariant[] = ["connecting", "tidal", "halo", "loxodrome", "nebula"];

export default function Page() {
  return (
    <main style={{ position: "relative", zIndex: 1, display: "flex", flexWrap: "wrap", gap: 24, padding: 24, background: "#000", minHeight: "100vh", color: "#e6e8eb" }}>
      {VARIANTS.map((v) => (
        <figure key={v} data-testid={`orb-${v}`} style={{ margin: 0, textAlign: "center" }}>
          <Orb px={220} variant={v} />
          <figcaption>{v}</figcaption>
        </figure>
      ))}
    </main>
  );
}
