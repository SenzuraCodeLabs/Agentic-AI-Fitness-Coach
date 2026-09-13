"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
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
  route?: string;
  tokens?: number;
}
const STARTERS = [
  {
    category: "BUILD MOMENTUM",
    title: "Break through a plateau",
    query: "My bench has stalled at 80kg",
    number: "01",
  },
  {
    category: "TRAIN SMARTER",
    title: "Understand progressive overload",
    query: "What is progressive overload?",
    number: "02",
  },
  {
    category: "KNOW YOUR EFFORT",
    title: "Make sense of RPE",
    query: "What does RPE mean?",
    number: "03",
  },
  {
    category: "YOUR TRAINING LOG",
    title: "Review my recent sessions",
    query: "Show me my progress",
    number: "04",
  },
];
const ROUTES: Record<string, string> = {
  predefined: "Quick answer",
  knowledge_base: "From the evidence library",
  deterministic: "Calculated from your workout",
  database: "From your training log",
  cache: "Saved answer",
  deepseek: "DeepSeek fallback",
  unavailable: "More detail needed",
};
export default function ChatPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "instant",
      block: "nearest",
    });
  }, [turns]);
  async function send(message: string) {
    const text = message.trim();
    if (!text || sending.current) return;
    sending.current = true;
    setBusy(true);
    setInput("");
    const id = crypto.randomUUID();
    setTurns((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", text },
      { id, role: "coach", text: "", status: "analysing" },
    ]);
    const patch = (changes: Partial<Turn>) =>
      setTurns((current) =>
        current.map((turn) =>
          turn.id === id ? { ...turn, ...changes } : turn,
        ),
      );
    try {
      await streamChat(text, {
        onStatus: (data) => patch({ status: String(data.stage ?? "") }),
        onDecision: (decision) => patch({ decision }),
        onMessage: (reply, citations, _terminal, route, tokens) =>
          patch({ text: reply, citations, route, tokens, status: undefined }),
        onDone: () => patch({ status: undefined }),
        onError: (error) => {
          patch({ error, status: undefined });
          setInput(text);
        },
      });
    } catch {
      patch({
        error:
          "Connection interrupted. Check your history before resending a workout; it may already be saved.",
        status: undefined,
      });
      setInput(text);
    } finally {
      sending.current = false;
      setBusy(false);
      inputRef.current?.focus();
    }
  }
  if (loading)
    return (
      <div className="card" role="status">
        Getting your workspace ready…
      </div>
    );
  if (!user) return null;
  const local = turns.filter(
    (t) =>
      t.role === "coach" &&
      t.route &&
      t.route !== "deepseek" &&
      t.route !== "unavailable",
  ).length;
  return (
    <div className="coach-workspace">
      <section className="coach-primary">
        <div className="workspace-heading">
          <div>
            <p className="eyebrow">YOUR PERSONAL TRAINING SPACE</p>
            <h1>
              Small steps.
              <br />
              <span>Stronger you.</span>
            </h1>
          </div>
          <span className="workspace-label">
            <span className="status-dot" /> Evidence-led coaching
          </span>
        </div>
        <p className="intro-copy">
          A clearer next step for every session. Log your lifts, understand your
          progress, and get advice with the evidence behind it.
        </p>
        <div className="conversation-card">
          <div className="conversation-header">
            <div className="flex items-center gap-3">
              <span className="coach-avatar" aria-hidden="true">
                F
              </span>
              <div>
                <strong>Your coach</strong>
                <p>Let’s make your next session count.</p>
              </div>
            </div>
            <span className="tag bg-green-50 text-ok">Ready when you are</span>
          </div>
          {turns.length === 0 ? (
            <div className="welcome-state">
              <p className="eyebrow">A GOOD PLACE TO START</p>
              <h2>What are we working on?</h2>
              <div className="starter-grid">
                {STARTERS.map((item) => (
                  <button
                    key={item.number}
                    className="starter-card"
                    onClick={() => send(item.query)}
                    disabled={busy}
                  >
                    <span className="starter-number">{item.number}</span>
                    <span className="eyebrow">{item.category}</span>
                    <strong>{item.title}</strong>
                    <span className="starter-arrow" aria-hidden="true">
                      ↗
                    </span>
                  </button>
                ))}
              </div>
              <p className="welcome-note">
                Or tell me what you trained today. Your own words work.
              </p>
            </div>
          ) : (
            <div
              className="conversation-messages"
              aria-live="polite"
              aria-relevant="additions text"
            >
              {turns.map((turn) =>
                turn.role === "user" ? (
                  <div key={turn.id} className="user-turn">
                    <p>{turn.text}</p>
                  </div>
                ) : (
                  <article key={turn.id} className="coach-turn">
                    <span className="eyebrow">FITCOACH</span>
                    {turn.status && (
                      <p role="status" className="text-muted">
                        {turn.status === "analysing"
                          ? "Checking your message…"
                          : turn.status === "logged"
                            ? "Workout saved. Finding your next step…"
                            : "Checking your log and evidence library…"}
                      </p>
                    )}
                    {turn.error && (
                      <p role="alert" className="text-danger">
                        {turn.error}
                      </p>
                    )}
                    {turn.text && <p className="reply-text">{turn.text}</p>}
                    {turn.route && (
                      <p className="answer-route">
                        {ROUTES[turn.route] ?? turn.route}
                        {turn.tokens !== undefined && (
                          <span>
                            {" "}
                            · {turn.tokens.toLocaleString()} API tokens
                          </span>
                        )}
                      </p>
                    )}
                    {turn.decision && (
                      <TransparencyPanel
                        decision={turn.decision}
                        citations={turn.citations}
                      />
                    )}
                  </article>
                ),
              )}
              <div ref={bottomRef} />
            </div>
          )}
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              send(input);
            }}
          >
            <label htmlFor="coach-message" className="sr-only">
              Message your coach
            </label>
            <textarea
              id="coach-message"
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="e.g. Squatted 60kg for 3 sets of 8 reps today…"
              maxLength={4000}
              rows={2}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  send(input);
                }
              }}
            />
            <div className="composer-footer">
              <span>Enter to send · Shift + Enter for a new line</span>
              <button className="btn-primary" disabled={busy || !input.trim()}>
                {busy ? "Working…" : "Send message ↗"}
              </button>
            </div>
          </form>
        </div>
      </section>
      <aside className="coach-sidebar">
        <div className="training-note">
          <span className="eyebrow">THE LONG GAME</span>
          <h2>
            Consistency
            <br />
            is your
            <br />
            <em>superpower.</em>
          </h2>
          <div className="progress-art" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
          </div>
          <p>
            One session at a time.
            <br />
            One decision backed by evidence.
          </p>
        </div>
        <div className="sidebar-section">
          <p className="eyebrow">BUILT AROUND YOUR TRAINING</p>
          <ol className="process-list">
            <li>
              <b>01</b>
              <div>
                <strong>Understand</strong>
                <p>Your message is checked and gym shorthand translated.</p>
              </div>
            </li>
            <li>
              <b>02</b>
              <div>
                <strong>Find the evidence</strong>
                <p>Your log and curated research come first.</p>
              </div>
            </li>
            <li>
              <b>03</b>
              <div>
                <strong>Choose a next step</strong>
                <p>
                  Workout numbers are calculated, with sources you can inspect.
                </p>
              </div>
            </li>
          </ol>
        </div>
        <div className="local-stat">
          <span className="eyebrow">THIS CONVERSATION</span>
          <strong>
            {local}
            <small> locally answered</small>
          </strong>
          <p>Saved answers and the evidence library help keep API use down.</p>
          <Link href="/telemetry">View your usage ↗</Link>
        </div>
      </aside>
    </div>
  );
}
