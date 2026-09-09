"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "@/app/providers";
import { getWorkouts, type WorkoutSession } from "@/lib/api";

export default function HistoryPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [sessions, setSessions] = useState<WorkoutSession[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    getWorkouts()
      .then((data) => setSessions(data.sessions))
      .catch(() => setError("Could not load your history."))
      .finally(() => setFetching(false));
  }, [user]);

  // Oldest first for the chart: a progression reads left to right.
  const chartData = useMemo(
    () =>
      [...sessions]
        .reverse()
        .map((session) => ({
          date: new Date(session.session_date).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
          }),
          tonnage: session.tonnage_kg,
        })),
    [sessions],
  );

  const totalTonnage = useMemo(
    () => sessions.reduce((sum, session) => sum + session.tonnage_kg, 0),
    [sessions],
  );

  if (loading || fetching) return <p className="text-muted">Loading...</p>;
  if (!user) return null;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">History</h1>
        <p className="text-sm text-muted">
          Tonnage is load multiplied by reps and sets, the standard measure of
          session workload.
        </p>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      {sessions.length === 0 ? (
        <div className="card text-sm text-muted">
          No sessions logged yet. Tell the coach what you trained.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div className="card">
              <div className="text-xs text-muted">Sessions</div>
              <div className="text-xl font-semibold">{sessions.length}</div>
            </div>
            <div className="card">
              <div className="text-xs text-muted">Total tonnage</div>
              <div className="text-xl font-semibold">
                {totalTonnage.toLocaleString()} kg
              </div>
            </div>
            <div className="card">
              <div className="text-xs text-muted">Average per session</div>
              <div className="text-xl font-semibold">
                {Math.round(totalTonnage / sessions.length).toLocaleString()} kg
              </div>
            </div>
          </div>

          <div className="card">
            <div className="mb-3 text-sm font-medium">Tonnage over time</div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date" fontSize={12} stroke="#6b7280" />
                  <YAxis fontSize={12} stroke="#6b7280" unit="kg" />
                  <Tooltip
                    formatter={(value: number) => [`${value} kg`, "Tonnage"]}
                  />
                  <Line
                    type="monotone"
                    dataKey="tonnage"
                    stroke="#1d4ed8"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card overflow-x-auto">
            <div className="mb-3 text-sm font-medium">Logged sessions</div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th className="pb-2 pr-4 font-medium">Date</th>
                  <th className="pb-2 pr-4 font-medium">Exercise</th>
                  <th className="pb-2 pr-4 font-medium">Load</th>
                  <th className="pb-2 pr-4 font-medium">Reps</th>
                  <th className="pb-2 pr-4 font-medium">Sets</th>
                  <th className="pb-2 pr-4 font-medium">RPE</th>
                  <th className="pb-2 font-medium">Tonnage</th>
                </tr>
              </thead>
              <tbody>
                {sessions.flatMap((session, sessionIndex) =>
                  session.sets.map((set, setIndex) => (
                    <tr
                      key={`${sessionIndex}-${setIndex}`}
                      className="border-b border-line last:border-0"
                    >
                      <td className="py-2 pr-4 text-muted">
                        {new Date(session.session_date).toLocaleDateString()}
                      </td>
                      <td className="py-2 pr-4">{set.exercise}</td>
                      <td className="py-2 pr-4">
                        {set.load_kg !== null ? `${set.load_kg} kg` : "-"}
                      </td>
                      <td className="py-2 pr-4">{set.reps ?? "-"}</td>
                      <td className="py-2 pr-4">{set.sets ?? "-"}</td>
                      <td className="py-2 pr-4">{set.rpe ?? "-"}</td>
                      <td className="py-2">
                        {setIndex === 0 ? `${session.tonnage_kg} kg` : ""}
                      </td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
