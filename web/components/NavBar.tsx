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
    <header className="app-header">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <div className="nav-inner">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            F
          </span>{" "}
          FitCoach<span className="brand-dot">.</span>
        </Link>

        {user && (
          <nav aria-label="Main navigation" className="main-nav">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                aria-current={pathname === link.href ? "page" : undefined}
                className={
                  pathname === link.href ? "nav-link active" : "nav-link"
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
