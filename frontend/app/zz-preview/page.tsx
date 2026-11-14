import localFont from "next/font/local";
import AurisLogo from "@/components/AurisLogo";
import Dashboard from "../dashboard/Dashboard";

const gambarino = localFont({ src: "../fonts/Gambarino-Regular.woff2" });

export const metadata = { title: "Auris — Dashboard" };

export default function Page() {
  return (
    <main style={{ position: "relative", minHeight: "100vh", color: "#e6e8eb" }}>
      {/* top 24 = the dock tiles' top edge (dock top 12 + (panelHeight 100 - item 76) / 2), so the heights line up. */}
      <div style={{ position: "fixed", top: 24, right: 40, zIndex: 20 }}>
        <AurisLogo fontFamily={gambarino.style.fontFamily} />
      </div>
      <Dashboard />
    </main>
  );
}
