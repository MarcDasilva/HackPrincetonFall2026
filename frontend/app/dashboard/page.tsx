import localFont from "next/font/local";
import AurisLogo from "@/components/AurisLogo";
import Dashboard from "./Dashboard";

const gambarino = localFont({ src: "../fonts/Gambarino-Regular.woff2" });

export const metadata = { title: "Auris — Dashboard" };

export default function Page() {
  return (
    <main style={{ position: "relative", minHeight: "100vh", color: "#e6e8eb" }}>
      {/* Vertically centered on the dock icons: icon center is 62 (dock top 12 + (panelHeight 100 - item 76) / 2 + 38), minus half the 48px logo. */}
      <div style={{ position: "fixed", top: 38, right: 40, zIndex: 20 }}>
        <AurisLogo fontFamily={gambarino.style.fontFamily} />
      </div>
      <Dashboard />
    </main>
  );
}
