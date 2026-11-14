import localFont from "next/font/local";
import Demo from "./Demo";

const gambarino = localFont({ src: "../fonts/Gambarino-Regular.woff2" });

export const metadata = { title: "Auris — Demo" };

export default function Page() {
  return <Demo fontFamily={gambarino.style.fontFamily} />;
}
