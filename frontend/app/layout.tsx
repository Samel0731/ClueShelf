import type { Metadata } from "next";
import "./globals.css";
import "./workspace.css";
import AppShell from "./app-shell";

export const metadata: Metadata = {
  title: "ClueShelf · 集緒",
  description: "把喜歡的收好，把需要的找回。你的跨平台個人收藏庫。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-Hant"><body><AppShell>{children}</AppShell></body></html>;
}
