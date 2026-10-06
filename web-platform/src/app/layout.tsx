import type { Metadata } from "next";
import { Inter, Tajawal } from "next/font/google";
import "./ghostbot-cyber.css";
import "./globals.css";
import GhostBotSvgSprite from "@/components/GhostBotSvgSprite";
import { AppShell } from "@/components/AppShell";
import { SupabaseProvider } from "@/components/SupabaseProvider";
import { LanguageProvider } from "@/context/LanguageContext";

const inter = Inter({ subsets: ["latin"] });
const tajawal = Tajawal({ subsets: ["arabic"], weight: ["400", "500", "700", "800", "900"] });

export const metadata: Metadata = {
  title: "GhostBot — Your Intelligent AI Companion",
  description: "GhostBot Tactical Cyber-Cyan Cloud Fleet Automation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ar" dir="rtl" className="dark">
      <body
        suppressHydrationWarning
        className={`${inter.className} ${tajawal.className} bg-[#040a17] text-[#d6eeff] antialiased min-h-screen selection:bg-[#00e5ff] selection:text-black`}
      >
        {/* GhostBot Kingdom Background Layers */}
        <div className="kingdom-bg-layer" />
        <div className="kingdom-brand-overlay" />

        {/* Master SVG Sprite Sheet */}
        <GhostBotSvgSprite />

        <LanguageProvider>
          <SupabaseProvider>
            <AppShell>{children}</AppShell>
          </SupabaseProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
