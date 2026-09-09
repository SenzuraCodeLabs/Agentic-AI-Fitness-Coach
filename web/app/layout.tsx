import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "./providers";
import { NavBar } from "@/components/NavBar";

export const metadata: Metadata = {
  title: "FitCoach",
  description: "Agentic AI strength coaching with transparent decisions",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <NavBar />
          <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
