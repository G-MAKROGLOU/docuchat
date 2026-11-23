import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@geomak/ui/styles";
import "./globals.css";
import { AppFrame } from "@/components/layout/AppFrame";

export const metadata: Metadata = {
  title: "DocuChat",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AppFrame>{children}</AppFrame>
      </body>
    </html>
  );
}
