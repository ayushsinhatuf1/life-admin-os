import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Life Admin OS — Family Record Intelligence",
  description: "Privacy-first, AI-assisted platform for family documents and deadlines.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-50 text-stone-900 antialiased">
        {children}
      </body>
    </html>
  );
}
