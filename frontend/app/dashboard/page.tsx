import Background from "@/components/Background";
import Dashboard from "./Dashboard";

export const metadata = { title: "Auris — Dashboard" };

export default function Page() {
  return (
    <main style={{ position: "relative", minHeight: "100vh", color: "#e6e8eb" }}>
      <Background />
      <Dashboard />
    </main>
  );
}
