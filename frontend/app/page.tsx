import localFont from "next/font/local";
import LandingHero from "@/components/LandingHero";

const gambarino = localFont({ src: "./fonts/Gambarino-Regular.woff2" });

export default function Home() {
  return (
    <main style={{ position: "relative" }}>
      <LandingHero fontFamily={gambarino.style.fontFamily} />
    </main>
  );
}
