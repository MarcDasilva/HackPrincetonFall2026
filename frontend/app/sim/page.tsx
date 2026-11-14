import SimGrid from "./SimGrid";

export const metadata = { title: "Auris — Scene grid" };

// Iteration route for the live scene grid (not linked from the dashboard yet).
export default function Page() {
  return (
    <main style={{ position: "relative", minHeight: "100vh", color: "#e6e8eb" }}>
      <SimGrid />
    </main>
  );
}
