import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@geomak/ui/styles";
import "./globals.css";

export const metadata: Metadata = {
  title: "Assistant",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
