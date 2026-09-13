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
              includes the preceding 24 hours.
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
                Workout calculations, predefined answers and strong evidence matches use no coaching API tokens. If enabled, the security judge can still spend tokens before a refusal.
              </li>
              <li>
                <span className="font-medium text-ink">Band-gated judge.</span>
                {" "}
                The paid classifier is disabled by default. When enabled, it runs only in the uncertain band. Rule and semantic checks remain local.
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
