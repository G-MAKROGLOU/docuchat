"use client";

import { AppShell, type SidebarSection, ThemeProvider, ThemeSwitch, TopBar } from "@geomak/ui";
import { ChartBar, Chat, Database, Document, Heart, Settings } from "@geomak/ui/icons";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { ChatProvider } from "@/components/chat/ChatProvider";
import { APP_NAME } from "@/lib/brand";
import styles from "./AppFrame.module.css";
import { Logo } from "./Logo";

export function AppFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [isDark, setDark] = useState(false);

  // Portals render outside the ThemeProvider wrapper, so the root element needs the class too.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
  }, [isDark]);

  const sections: SidebarSection[] = [
    {
      key: "main",
      items: [
        {
          key: "chat",
          label: "Chat",
          icon: <Chat size={18} />,
          isActive: pathname === "/",
          onClick: () => router.push("/"),
        },
        {
          key: "documents",
          label: "Documents",
          icon: <Document size={18} />,
          isActive: pathname === "/documents",
          onClick: () => router.push("/documents"),
        },
        {
          key: "corpus",
          label: "Corpus",
          icon: <Database size={18} />,
          isActive: pathname === "/corpus",
          onClick: () => router.push("/corpus"),
        },
        {
          key: "status",
          label: "Status",
          icon: <ChartBar size={18} />,
          isActive: pathname === "/status",
          onClick: () => router.push("/status"),
        },
        {
          key: "health",
          label: "Health",
          icon: <Heart size={18} />,
          isActive: pathname === "/health",
          onClick: () => router.push("/health"),
        },
        {
          key: "settings",
          label: "Settings",
          icon: <Settings size={18} />,
          isActive: pathname === "/settings",
          onClick: () => router.push("/settings"),
        },
      ],
    },
  ];

  return (
    <ThemeProvider colorScheme={isDark ? "dark" : "light"}>
      <AppShell
        topBar={
          <TopBar
            brand={
              <span className={styles.brand}>
                <Logo />
                <strong>{APP_NAME}</strong>
              </span>
            }
            actions={
              <ThemeSwitch checked={isDark} onChange={({ target }) => setDark(target.checked)} />
            }
          />
        }
        sidebarSections={sections}
      >
        <ChatProvider>{children}</ChatProvider>
      </AppShell>
    </ThemeProvider>
  );
}
