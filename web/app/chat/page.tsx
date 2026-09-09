"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/app/providers";
import { streamChat, type Citation, type DecisionEvent } from "@/lib/api";
import { TransparencyPanel } from "@/components/TransparencyPanel";

interface Turn {
  id: string;
  role: "user" | "coach";
  text: string;
  decision?: DecisionEvent;
  citations?: Citation[];
  status?: string;
  error?: string;
  terminal?: boolean;
}

const EXAMPLES = [
  "Squatted 100kg for 5 reps today",
  "How many sets per muscle group per week?",
  "My bench has stalled at 80kg",
];

export default function ChatPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function send(message: string) {
    const text = message.trim();
    if (!text || busy) return;

    setBusy(true);
    setInput("");

    const coachId = crypto.randomUUID();
    setTurns((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text },
      { id: coachId, role: "coach", text: "", status: "analysing" },
    ]);

    const patch = (changes: Partial<Turn>) =>
      setTurns((current) =>
        current.map((turn) =>
          turn.id === coachId ? { ...turn, ...changes } : turn,
        ),
      );

    await streamChat(text, {
      onStatus: (data) => patch({ status: String(data.stage ?? "") }),
      onDecision: (decision) => patch({ decision }),
      onMessage: (replyText, citations, terminal) =>
        patch({ text: replyText, citations, terminal, status: undefined }),
      onDone: () => patch({ status: undefined }),
      onError: (message) => patch({ error: message, status: undefined }),
    });

    setBusy(false);
  }

  if (loading) return <p className="text-muted">Loading...</p>;
  if (!user) return null;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Coach</h1>
        <p className="text-sm text-muted">
          Log a session in plain language, or ask about your training. Every
          reply shows how the decision was reached.
        </p>
      </div>

      {turns.length === 0 && (
        <div className="card">
          <div className="mb-2 text-sm font-medium">Try one of these</div>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => send(example)}
                className="btn-secondary text-xs"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-3">
        {turns.map((turn) =>
          turn.role === "user" ? (
            <div key={turn.id} className="flex justify-end">
              <div className="max-w-[80%] rounded-lg bg-ink px-4 py-2 text-sm text-white">
                {turn.text}
              </div>
            </div>
          ) : (
            <div key={turn.id} className="max-w-[85%]">
              <div className="rounded-lg border border-line bg-white px-4 py-3 text-sm">
                {turn.status && (
                  <span className="text-muted">
                    {turn.status === "analysing" && "Checking your message..."}
                    {turn.status === "logged" && "Session logged."}
                    {turn.status === "coaching" && "Working out your next step..."}
                  </span>
                )}
                {turn.error && <span className="text-danger">{turn.error}</span>}
                {turn.text && (
                  <p className="whitespace-pre-wrap">{turn.text}</p>
                )}
              </div>
              {turn.decision && (
                <TransparencyPanel
                  decision={turn.decision}
                  citations={turn.citations}
                />
              )}
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
        className="sticky bottom-0 flex gap-2 bg-surface pt-3"
      >
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Squatted 100kg for 5 reps today"
          maxLength={4000}
          className="field"
          disabled={busy}
        />
        <button type="submit" className="btn-primary" disabled={busy || !input.trim()}>
          {busy ? "..." : "Send"}
        </button>
      </form>
    </div>
  );
}
