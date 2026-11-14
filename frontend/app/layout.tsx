import type { Metadata } from "next";
import "./globals.css";
import Backdrop from "@/components/Backdrop";

export const metadata: Metadata = { title: "Auris" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <Backdrop />
        {children}
      </body>
    </html>
  );
}
