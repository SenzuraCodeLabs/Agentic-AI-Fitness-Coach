"use client";

import { useState } from "react";
import Link from "next/link";
import { ApiError, register } from "@/lib/api";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      // The timezone is captured so "yesterday" resolves to the right date for
      // this user rather than the server's locale.
      const timezone =
        Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const result = await register(email, password, timezone);
      setDone(result.message);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.detail : "Could not register.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="mx-auto max-w-sm">
        <div className="card">
          <h1 className="mb-2 text-lg font-semibold">Check your inbox</h1>
          <p className="text-sm text-muted">{done}</p>
          <Link href="/login" className="mt-4 inline-block text-sm text-accent hover:underline">
            Go to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="mb-1 text-lg font-semibold">Create an account</h1>
      <p className="mb-4 text-sm text-muted">
        Log your training in plain language.
      </p>

      <form onSubmit={submit} className="card space-y-4">
        <div>
          <label className="label" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="field"
          />
        </div>

        <div>
          <label className="label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={10}
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="field"
          />
          <p className="mt-1 text-xs text-muted">
            At least 10 characters, mixing letters with numbers or symbols.
          </p>
        </div>

        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}

        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? "Creating..." : "Create account"}
        </button>
      </form>

      <p className="mt-4 text-center text-sm text-muted">
        Already registered?{" "}
        <Link href="/login" className="text-accent hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
