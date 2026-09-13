"use client";

import { useState } from "react";
import type { Citation, DecisionEvent } from "@/lib/api";

/**
 * Per-reply transparency panel. This IS the explainability deliverable.
 *
 * It shows what the Gatekeeper concluded and why: the classified intent, the
 * risk score with its per-signal breakdown, which policy rule fired, and which
 * sources the answer drew on. A user can see the reasoning behind a refusal
 * without being told which detector to evade, because reason codes describe
 * categories rather than patterns.
 */

const DECISION_STYLES: Record<string, string> = {
  ALLOW: "bg-green-50 text-ok border-green-200",
  SANITISE: "bg-amber-50 text-warn border-amber-200",
  CLARIFY: "bg-blue-50 text-accent border-blue-200",
  REFUSE_MEDICAL: "bg-amber-50 text-warn border-amber-200",
  BLOCK: "bg-red-50 text-danger border-red-200",
};

function riskColour(score: number) {
  if (score >= 0.75) return "bg-danger";
  if (score >= 0.5) return "bg-warn";
  if (score >= 0.15) return "bg-yellow-400";
  return "bg-ok";
}

export function TransparencyPanel({
  decision,
  citations,
}: {
  decision: DecisionEvent;
  citations?: Citation[];
}) {
  const [open, setOpen] = useState(false);
  const style =
    DECISION_STYLES[decision.decision] ?? "bg-surface text-muted border-line";

  return (
    <div className="mt-2 text-xs">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full flex-wrap items-center gap-2 text-left text-muted hover:text-ink"
        aria-expanded={open}
      >
        <span className={`tag border ${style}`}>{decision.decision}</span>
        <span className="font-medium">{decision.intent}</span>
        <span>risk {decision.risk_score.toFixed(2)}</span>
        <span className="text-line">|</span>
        <span>{decision.pipeline_ms.toFixed(0)}ms</span>
        <span className="ml-auto">{open ? "hide detail" : "why?"}</span>
      </button>

      {open && (
        <div className="mt-2 space-y-3 rounded-md border border-line bg-white p-3">
          <div>
            <div className="mb-1 font-medium text-ink">Risk score</div>
            <div className="h-2 w-full overflow-hidden rounded bg-line">
              <div
                className={`h-full ${riskColour(decision.risk_score)}`}
                style={{ width: `${decision.risk_score * 100}%` }}
              />
            </div>
            <div className="mt-1 text-muted">
              Blocked at 0.75, sanitised from 0.50
            </div>
          </div>

          <div>
            <div className="mb-1 font-medium text-ink">Detector signals</div>
            <table className="w-full">
              <tbody>
                {Object.entries(decision.signal_contributions).map(
                  ([signal, value]) => (
                    <tr key={signal}>
                      <td className="py-0.5 pr-3 capitalize text-muted">
                        {signal}
                      </td>
                      <td className="py-1 font-mono">
                        {decision.signal_status?.[signal] &&
                        decision.signal_status[signal] !== "completed"
                          ? ({
                              disabled: "Disabled · local checks active",
                              outside_band: "Not needed",
                              unavailable: "Unavailable",
                            }[decision.signal_status[signal]] ?? "Not run")
                          : value.toFixed(3)}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            <div className="mt-1 text-muted">
              Combined by maximum, so one confident signal is enough.
              {decision.semantic_similarity !== undefined && (
                <p className="mt-1">
                  Raw semantic similarity:{" "}
                  {decision.semantic_similarity.toFixed(3)}. Values below 0.45
                  contribute zero risk.
                </p>
              )}
            </div>
          </div>

          <div>
            <div className="mb-1 font-medium text-ink">Policy rule</div>
            <code className="rounded bg-surface px-1.5 py-0.5">
              {decision.policy_rule_id}
            </code>
          </div>

          {decision.reason_codes.length > 0 && (
            <div>
              <div className="mb-1 font-medium text-ink">Reason codes</div>
              <div className="flex flex-wrap gap-1">
                {decision.reason_codes.map((code) => (
                  <span key={code} className="tag bg-surface text-muted">
                    {code}
                  </span>
                ))}
              </div>
            </div>
          )}

          {decision.extraction_confidence !== null && (
            <div>
              <div className="mb-1 font-medium text-ink">
                Extraction confidence
              </div>
              <span className="font-mono">
                {decision.extraction_confidence.toFixed(2)}
              </span>
              <span className="ml-2 text-muted">
                below 0.55 the system asks rather than guesses
              </span>
            </div>
          )}

          {citations && citations.length > 0 && (
            <div>
              <div className="mb-1 font-medium text-ink">Sources retrieved</div>
              <ul className="space-y-1">
                {citations.map((citation, index) => (
                  <li key={index} className="border-l-2 border-line pl-2">
                    <div className="font-medium">
                      {citation.url && /^https:\/\//i.test(citation.url) ? (
                        <a
                          className="underline underline-offset-2"
                          href={citation.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {citation.source} ↗
                        </a>
                      ) : (
                        citation.source
                      )}
                    </div>
                    <div className="text-muted">{citation.snippet}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
