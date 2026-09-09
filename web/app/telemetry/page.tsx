"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/app/providers";
import { getTelemetry } from "@/lib/api";

interface Quota {
  used: number;
  limit: number;
  remaining: number;
}

export default function TelemetryPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [quota, setQuota] = useState<Quota | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    getTelemetry()
      .then((data) => setQuota(data.quota))
      .catch(() => setError("Could not load usage."));
  }, [user]);

  if (loading) return <p className="text-muted">Loading...</p>;
  if (!user) return null;

  const percentage = quota ? Math.min((quota.used / quota.limit) * 100, 100) : 0;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">Usage</h1>
        <p className="text-sm text-muted">
          Language-model tokens spent on your account in the last 24 hours.
          Requests are cheap; tokens are not, so the quota is what bounds cost.
        </p>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      {quota && (
        <>
          <div className="card">
            <div className="mb-2 flex items-baseline justify-between">
              <span className="text-sm font-medium">Daily token quota</span>
              <span className="text-sm text-muted">
                {quota.used.toLocaleString()} of {quota.limit.toLocaleString()}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded bg-line">
              <div
                className={percentage > 80 ? "h-full bg-warn" : "h-full bg-accent"}
                style={{ width: `${Math.max(percentage, 1)}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-muted">
              {quota.remaining.toLocaleString()} tokens remaining. The window
              rolls 24 hours from your first request.
            </p>
          </div>

          <div className="card">
            <div className="mb-2 text-sm font-medium">How usage is controlled</div>
            <ul className="space-y-2 text-sm text-muted">
              <li>
                <span className="font-medium text-ink">Rate limit.</span> A
                sliding window per user and per address, so a burst cannot
                exceed the limit by straddling a clock boundary.
              </li>
              <li>
                <span className="font-medium text-ink">Short circuit.</span>
                {" "}
                A blocked or refused message never reaches the language model,
                so an attack costs nothing to serve.
              </li>
              <li>
                <span className="font-medium text-ink">Band-gated judge.</span>
                {" "}
                The language-model classifier runs only when the cheap
                detectors are uncertain, which was about 6 percent of messages
                in benchmarking.
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
