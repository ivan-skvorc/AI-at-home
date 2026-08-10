import "@/styles/globals.css";

import { type Metadata, type Viewport } from "next";

import { ReduceMotionEffect } from "@/components/reduce-motion-effect";
import { ThemeProvider } from "@/components/theme-provider";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

export const metadata: Metadata = {
  title: "DeerFlow",
  description: "A LangChain-based framework for building super agents.",
  // Fork feature: installable to a phone home screen, which is also what makes
  // iOS deliver Web Push at all — iOS only pushes to installed web apps.
  manifest: "/manifest.webmanifest",
  applicationName: "DeerFlow",
  appleWebApp: {
    capable: true,
    title: "DeerFlow",
    statusBarStyle: "default",
  },
  icons: {
    icon: "/icons/icon-192.png",
    apple: "/icons/icon-192.png",
  },
};

export const viewport: Viewport = {
  themeColor: "#1f6feb",
  // The chat composer is a fixed-position input; without viewport-fit the iOS
  // home-bar overlaps it in an installed PWA.
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang={DEFAULT_LOCALE}
      suppressContentEditableWarning
      suppressHydrationWarning
    >
      <body>
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          <ReduceMotionEffect />
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
