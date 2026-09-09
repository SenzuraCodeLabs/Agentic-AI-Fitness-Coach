"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/app/providers";

const LINKS = [
  { href: "/chat", label: "Coach" },
  { href: "/history", label: "History" },
  { href: "/telemetry", label: "Usage" },
];

export function NavBar() {
  const { user, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
        <Link href="/" className="text-base font-semibold">
          FitCoach
        </Link>

        {user && (
          <nav className="flex gap-4 text-sm">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={
                  pathname === link.href
                    ? "font-medium text-ink"
                    : "text-muted hover:text-ink"
                }
              >
                {link.label}
              </Link>
            ))}
          </nav>
        )}

        <div className="ml-auto flex items-center gap-3 text-sm">
          {user ? (
            <>
              {!user.email_verified && (
                <span className="tag bg-amber-50 text-warn">
                  email unverified
                </span>
              )}
              <span className="text-muted">{user.display_name}</span>
              <button
                onClick={async () => {
                  await signOut();
                  router.push("/login");
                }}
                className="text-muted hover:text-ink"
              >
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" className="text-muted hover:text-ink">
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
