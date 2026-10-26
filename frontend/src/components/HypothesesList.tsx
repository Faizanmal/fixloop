"use client";

import React, { useState } from "react";
import { DiagnoseResponse } from "@/lib/api";
import {
  Lightbulb,
  CheckCircle2,
  XCircle,
  HelpCircle,
  ArrowRight,
  Shield,
  Wrench,
  AlertTriangle,
} from "lucide-react";
import { Progress } from "@/components/ui/progress";

interface HypothesesListProps {
  diagnosis: DiagnoseResponse;
  onProceedToPatch: () => void;
  canPatch: boolean;
}

export function HypothesesList({
  diagnosis,
  onProceedToPatch,
  canPatch,
}: HypothesesListProps) {
  const [selectedHypothesisIndex, setSelectedHypothesisIndex] = useState<number>(0);

  const hypotheses = diagnosis.hypotheses || [];
  const activeHypothesis = hypotheses[selectedHypothesisIndex] || hypotheses[0];
  const confidencePct = Math.round(diagnosis.confidence * 100);

  const isConclusive =
    diagnosis.status === "diagnosis_available" && diagnosis.confidence >= 0.9;
  const isInsufficient = diagnosis.status === "insufficient_evidence";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm backdrop-blur mb-8">
      {/* Header: Diagnosis Status & Confidence Gauge */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-mono font-bold tracking-wide uppercase border ${
                isConclusive
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                  : isInsufficient
                  ? "bg-purple-500/10 text-purple-400 border-purple-500/30"
                  : "bg-amber-500/10 text-amber-400 border-amber-500/30"
              }`}
            >
              {diagnosis.status.replace(/_/g, " ")}
            </span>
            <span className="text-xs text-slate-400 font-mono">
              Next Action: {diagnosis.next_action}
            </span>
          </div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <Lightbulb className="h-5 w-5 text-amber-400" />
            Root-Cause Hypotheses & Confidence Calibration
          </h3>
          <p className="text-xs text-slate-300 mt-0.5">
            {diagnosis.summary}
          </p>
        </div>

        {/* Calibrated Confidence Gauge */}
        <div className="flex items-center gap-3 bg-black/50 border border-slate-800 rounded-xl px-4 py-2.5 self-start sm:self-center">
          <div>
            <div className="text-[10px] uppercase font-mono text-slate-400">
              Calibrated Confidence
            </div>
            <div className="text-xl font-bold font-mono text-white flex items-baseline gap-1.5">
              <span
                className={
                  confidencePct >= 90
                    ? "text-emerald-400"
                    : confidencePct >= 70
                    ? "text-amber-400"
                    : "text-purple-400"
                }
              >
                {confidencePct}%
              </span>
              <span className="text-xs text-slate-400 font-normal">
                {isConclusive ? "(Conclusive)" : "(High Uncertainty)"}
              </span>
            </div>
          </div>
          <div className="w-20">
            <Progress
              value={confidencePct}
              indicatorClassName={
                confidencePct >= 90
                  ? "bg-emerald-400"
                  : confidencePct >= 70
                  ? "bg-amber-400"
                  : "bg-purple-400"
              }
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Ranked Hypotheses Selector (5 cols) */}
        <div className="lg:col-span-5 space-y-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">
            Ranked Hypotheses ({hypotheses.length})
          </span>

          {hypotheses.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-800 p-6 text-xs text-slate-500 font-mono text-center">
              No hypotheses formulated. Provide logs or run an investigation.
            </div>
          ) : (
            hypotheses.map((hyp, idx) => {
              const isSelected = selectedHypothesisIndex === idx;
              const hypPct = Math.round(hyp.confidence * 100);
              const hypId = hyp.id || `HYP-${idx + 1}`;
              const supporting = hyp.supporting_evidence || [];
              const contradicting = hyp.contradicting_evidence || hyp.refuting_evidence || [];

              return (
                <div
                  key={hypId}
                  onClick={() => setSelectedHypothesisIndex(idx)}
                  className={`rounded-lg border p-3.5 cursor-pointer transition-all ${
                    isSelected
                      ? "border-cyan-500 bg-cyan-950/20 ring-1 ring-cyan-500/40 shadow-sm"
                      : "border-slate-800 bg-slate-950/40 hover:border-slate-700 hover:bg-slate-900/60"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-[11px] font-bold text-cyan-300">
                      #{idx + 1} • {hypId}
                    </span>
                    <span
                      className={`font-mono text-xs font-semibold ${
                        hypPct >= 90
                          ? "text-emerald-400"
                          : hypPct >= 70
                          ? "text-amber-400"
                          : "text-purple-400"
                      }`}
                    >
                      {hypPct}% Confidence
                    </span>
                  </div>
                  <p className="text-xs text-slate-200 font-medium line-clamp-2 leading-relaxed mb-3">
                    {hyp.description}
                  </p>
                  <div className="flex items-center gap-3 text-[11px] text-slate-400">
                    <span className="flex items-center gap-1 text-emerald-400">
                      <CheckCircle2 className="h-3 w-3" />
                      {supporting.length} Supporting
                    </span>
                    <span className="flex items-center gap-1 text-rose-400">
                      <XCircle className="h-3 w-3" />
                      {contradicting.length} Contradicting
                    </span>
                  </div>
                </div>
              );
            })
          )}

          {/* Missing Information Callout */}
          {diagnosis.missing_information && diagnosis.missing_information.length > 0 && (
            <div className="rounded-lg border border-purple-800/50 bg-purple-950/20 p-3.5 mt-4">
              <div className="flex items-center gap-1.5 text-xs font-bold text-purple-300 mb-2">
                <HelpCircle className="h-4 w-4" />
                Missing Information & Unobserved State
              </div>
              <ul className="list-disc list-inside space-y-1.5 text-slate-300 text-[11px] leading-relaxed">
                {diagnosis.missing_information.map((info, i) => (
                  <li key={i}>{info}</li>
                ))}
              </ul>
              <div className="mt-2 text-[10px] text-purple-400 font-mono">
                Engine will not invent guesses for unobserved external state.
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Active Hypothesis Evidence & Discriminating Tests (7 cols) */}
        <div className="lg:col-span-7 flex flex-col justify-between">
          {activeHypothesis ? (
            <div className="space-y-4">
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 block mb-1">
                  Active Hypothesis Detailed Breakdown
                </span>
                <div className="rounded-lg border border-slate-800 bg-black/50 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-xs text-cyan-400 font-bold">
                      {activeHypothesis.id || `HYP-${selectedHypothesisIndex + 1}`}
                    </span>
                    <span className="font-mono text-xs text-slate-300 bg-slate-800 px-2 py-0.5 rounded">
                      Calibrated Confidence: {((activeHypothesis.confidence ?? 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="text-sm text-slate-100 font-medium leading-relaxed">
                    {activeHypothesis.description}
                  </p>
                </div>
              </div>

              {/* Supporting Evidence Drilldown */}
              <div>
                <span className="text-xs font-semibold uppercase tracking-wider text-emerald-400 block mb-2 flex items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Supporting Evidence ({(activeHypothesis.supporting_evidence || []).length})
                </span>
                {(activeHypothesis.supporting_evidence || []).length === 0 ? (
                  <p className="text-xs text-slate-500 font-mono">None documented.</p>
                ) : (
                  <div className="space-y-1.5">
                    {activeHypothesis.supporting_evidence.map((sup, i) => (
                      <div
                        key={i}
                        className="rounded border border-emerald-900/40 bg-emerald-950/20 p-2 text-xs text-emerald-200 font-mono"
                      >
                        {sup}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Contradicting Evidence Drilldown */}
              {((activeHypothesis.contradicting_evidence || activeHypothesis.refuting_evidence || []).length > 0) && (
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-rose-400 block mb-2 flex items-center gap-1">
                    <XCircle className="h-3.5 w-3.5" />
                    Contradicting / Refuting Evidence (
                    {(activeHypothesis.contradicting_evidence || activeHypothesis.refuting_evidence || []).length})
                  </span>
                  <div className="space-y-1.5">
                    {(activeHypothesis.contradicting_evidence || activeHypothesis.refuting_evidence || []).map((ref, i) => (
                      <div
                        key={i}
                        className="rounded border border-rose-900/40 bg-rose-950/20 p-2 text-xs text-rose-200 font-mono"
                      >
                        {ref}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Discriminating Test for this Hypothesis */}
              {activeHypothesis.recommended_discriminating_test && (
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-cyan-400 block mb-1.5 flex items-center gap-1">
                    <Wrench className="h-3.5 w-3.5 text-cyan-400" />
                    Recommended Discriminating Test
                  </span>
                  <div className="rounded border border-cyan-800/40 bg-cyan-950/20 p-2.5 text-xs text-cyan-200 font-mono">
                    {activeHypothesis.recommended_discriminating_test}
                  </div>
                </div>
              )}

              {/* Recommended Next Tests List from Diagnosis */}
              {diagnosis.recommended_tests && diagnosis.recommended_tests.length > 0 && (
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-300 block mb-2 flex items-center gap-1">
                    <Wrench className="h-3.5 w-3.5 text-indigo-400" />
                    Recommended Allowlisted Tests ({diagnosis.recommended_tests.length})
                  </span>
                  <div className="space-y-2">
                    {diagnosis.recommended_tests.map((test, i) => (
                      <div
                        key={test.id || i}
                        className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 flex items-start justify-between gap-3 text-xs"
                      >
                        <div>
                          <div className="font-mono font-bold text-cyan-300 flex items-center gap-2">
                            <span>{test.test_type}</span>
                            <span className="text-slate-400 font-normal">&rarr; {test.target}</span>
                          </div>
                          <div className="text-slate-300 text-[11px] mt-1">
                            {test.description}
                          </div>
                          <div className="text-emerald-400 text-[10px] font-mono mt-1">
                            {test.expected_signal}
                          </div>
                        </div>
                        <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-mono text-slate-300 whitespace-nowrap">
                          {test.safety_level || "ALLOWLISTED"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="p-8 text-center text-xs text-slate-500 font-mono">
              Select a hypothesis on the left to inspect evidence.
            </div>
          )}

          {/* Bottom Action Bar */}
          <div className="pt-5 mt-6 border-t border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
              {isConclusive ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
                  <span>Conclusive evidence threshold (&gt;= 90%) met. Ready for minimal patch proposal.</span>
                </>
              ) : (
                <>
                  <AlertTriangle className="h-4 w-4 text-purple-400 shrink-0" />
                  <span>High uncertainty ({confidencePct}%). Automated patch generation strictly prevented.</span>
                </>
              )}
            </div>

            {canPatch ? (
              <button
                onClick={onProceedToPatch}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 py-2 text-xs font-semibold text-white shadow-md shadow-emerald-950/40 hover:from-emerald-400 hover:to-teal-500 transition-all cursor-pointer font-mono shrink-0"
              >
                <span>Review Patch & Verify in Sandbox</span>
                <ArrowRight className="h-4 w-4" />
              </button>
            ) : (
              <div className="inline-flex items-center gap-1.5 rounded-lg border border-purple-800/60 bg-purple-950/40 px-3 py-1.5 text-xs font-medium text-purple-300 shrink-0">
                <Shield className="h-3.5 w-3.5" />
                <span>Automated Patch Blocked (Safety Guard)</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
