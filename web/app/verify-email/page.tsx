"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_BASE } from "@/lib/api";

function VerifyEmailInner() {
  const params = useSearchParams();
  const token = params.get("token");
  const [state, setState] = useState<"working" | "ok" | "failed">("working");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setState("failed");
      setMessage("This link is missing its token.");
      return;
    }
    fetch(`${API_BASE}/api/auth/verify-email?token=${encodeURIComponent(token)}`, {
      method: "POST",
    })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (response.ok) {
          setState("ok");
          setMessage(body.message ?? "Your email address is confirmed.");
        } else {
          setState("failed");
          setMessage(body.detail ?? "This link is invalid or already used.");
        }
      })
      .catch(() => {
        setState("failed");
        setMessage("Could not reach the server.");
      });
  }, [token]);

  return (
    <div className="mx-auto max-w-sm">
      <div className="card">
        <h1 className="mb-2 text-lg font-semibold">
          {state === "working" && "Confirming..."}
          {state === "ok" && "Email confirmed"}
          {state === "failed" && "Could not confirm"}
        </h1>
        <p className="text-sm text-muted">{message}</p>
        <Link href="/login" className="mt-4 inline-block text-sm text-accent hover:underline">
          Go to sign in
        </Link>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<p className="text-muted">Loading...</p>}>
      <VerifyEmailInner />
    </Suspense>
  );
}
