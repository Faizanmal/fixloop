"use client";

import React from "react";
import { DiagnoseResponse } from "@/lib/api";
import {
  Clock,
  Terminal,
  Activity,
  Check,
  ShieldCheck,
  Zap,
  AlertCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface DiagnosticTimelineProps {
  diagnosis: DiagnoseResponse | null;
  isInvestigating: boolean;
  hasPatchVerified: boolean;
}

export function DiagnosticTimeline({
  diagnosis,
  isInvestigating,
  hasPatchVerified,
}: DiagnosticTimelineProps) {
  const probesCount = diagnosis?.audit_log?.probes_executed?.length ?? (
    diagnosis?.evidence.filter((e) => e.source.includes("probe") || e.source.includes("tool:")).length ?? 0
  );

  const steps = [
    {
      id: 1,
      name: "Evidence Ingestion",
      desc: "Container logs & inspect metadata parsed safely without disclosing secrets",
      completed: !!diagnosis || isInvestigating,
      active: isInvestigating && !diagnosis,
    },
    {
      id: 2,
      name: "Configuration Audit",
      desc: "Docker Compose, Dockerfile & environment variables inspected",
      completed: !!diagnosis,
      active: false,
    },
    {
      id: 3,
      name: "Active Probing",
      desc: probesCount > 0
        ? `${probesCount} allowlisted HTTP/TCP probe(s) dispatched`
        : diagnosis?.status === "insufficient_evidence"
        ? "Local probes evaluated and exhausted; external dependency prevented local deterministic probing"
        : "Probing evaluated (no active probe required for deterministic crash)",
      completed: !!diagnosis,
      active: false,
    },
    {
      id: 4,
      name: "Hypothesis Ranking",
      desc: "Evidence-weighted calibrated confidence & uncertainty bounds formulated",
      completed: !!diagnosis,
      active: false,
    },
    {
      id: 5,
      name: "Sandbox Verification",
      desc: "Tested in disposable ephemeral sandbox with host repository untouched",
      completed: hasPatchVerified,
      active: false,
    },
  ];

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 mb-8 backdrop-blur">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2.5 py-0.5 text-xs font-mono font-bold text-cyan-400">
              STATE MACHINE PROGRESSION
            </span>
            {isInvestigating ? (
              <Badge variant="warning" className="animate-pulse">
                Active Diagnostic Cycle Running...
              </Badge>
            ) : diagnosis ? (
              <Badge variant="success">Investigation Completed</Badge>
            ) : null}
          </div>
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Activity className="h-4 w-4 text-cyan-400" />
            Diagnostic Timeline & Investigation Lifecycle
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Strict allowlist execution bounds. Bounded iterations prevent runaway tool loops.
          </p>
        </div>

        {diagnosis?.audit_log?.stop_reason && (
          <span className="text-xs font-mono text-cyan-300 bg-cyan-950/60 border border-cyan-800/60 px-3 py-1.5 rounded-lg self-start sm:self-center">
            Stop: {diagnosis.audit_log.stop_reason}
          </span>
        )}
      </div>

      {/* Stepper Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        {steps.map((st) => (
          <div
            key={st.id}
            className={`flex flex-col justify-between p-3.5 rounded-lg border transition-all ${
              st.completed
                ? "border-emerald-800/60 bg-emerald-950/20 text-emerald-300 shadow-sm"
                : st.active
                ? "border-cyan-500 bg-cyan-950/30 text-cyan-200 animate-pulse ring-1 ring-cyan-500/50"
                : "border-slate-800 bg-slate-900/60 text-slate-500"
            }`}
          >
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-mono font-bold">Step {st.id}</span>
                {st.completed ? (
                  <Check className="h-4 w-4 text-emerald-400" />
                ) : st.active ? (
                  <div className="h-2 w-2 rounded-full bg-cyan-400 animate-ping" />
                ) : (
                  <Clock className="h-3.5 w-3.5 text-slate-600" />
                )}
              </div>
              <span className="text-xs font-semibold text-slate-200 block mb-1">
                {st.name}
              </span>
              <p className="text-[10px] text-slate-400 leading-relaxed">
                {st.desc}
              </p>
            </div>
          </div>
        ))}
      </div>

      {/* Active Probes Terminal Log */}
      {diagnosis && (
        <div className="mt-3 rounded-lg border border-slate-800 bg-black/60 p-3.5 font-mono text-xs">
          <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-2 mb-2">
            <span className="flex items-center gap-1.5 text-slate-300 font-semibold">
              <Terminal className="h-3.5 w-3.5 text-cyan-400" />
              Diagnostic Trace & Allowlisted Probe Evidence
            </span>
            <span className="text-[10px] text-slate-500">
              Zero Arbitrary Host Execution • Allowlist Only
            </span>
          </div>

          <div className="space-y-1.5 max-h-40 overflow-y-auto text-slate-300 text-[11px] py-1">
            {/* Show Probes from audit log or evidence */}
            {diagnosis.evidence
              .filter((e) => e.source.includes("probe") || e.source.includes("tool:"))
              .map((probe, i) => (
                <div key={`p-${i}`} className="flex items-start gap-2 text-cyan-300 bg-cyan-950/20 p-1.5 rounded border border-cyan-900/40">
                  <Zap className="h-3.5 w-3.5 text-cyan-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="text-cyan-400 font-bold mr-1.5">[PROBE EXECUTED]</span>
                    <span className="font-semibold text-slate-200">{probe.source}:</span>
                    <span className="ml-1 text-cyan-200">{probe.content}</span>
                  </div>
                </div>
              ))}

            {/* If no active probe was required */}
            {diagnosis.evidence.filter((e) => e.source.includes("probe") || e.source.includes("tool:")).length === 0 && (
              diagnosis.status === "insufficient_evidence" ? (
                <div className="text-purple-300 bg-purple-950/20 p-2.5 rounded border border-purple-800/40 text-[11px] space-y-1">
                  <div className="flex items-center gap-1.5 font-semibold text-purple-400">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    <span>Investigation Inconclusive: Insufficient Empirical Evidence</span>
                  </div>
                  <p className="text-slate-300">
                    <strong className="text-slate-200">Established: </strong>
                    Initial logs and container state were audited, but no deterministic configuration crash or reproducible error signature was found.
                  </p>
                  <p className="text-slate-300">
                    <strong className="text-slate-200">Unresolved: </strong>
                    Competing hypotheses remain inconclusive; safety invariant prevented synthesizing an unverified patch.
                  </p>
                  <p className="text-purple-200">
                    <strong className="text-purple-300">Recommended Next Steps: </strong>
                    {diagnosis.missing_information && diagnosis.missing_information.length > 0
                      ? `Provide ${diagnosis.missing_information.join(", ")}.`
                      : "Provide additional container runtime logs, stack traces, or environment configurations to disambiguate hypotheses."}
                  </p>
                </div>
              ) : (
                <div className="text-slate-400 p-1 flex items-center gap-1.5 text-[11px]">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                  <span>Diagnostic Engine verified root cause deterministically from initial evidence. No active network probes were required.</span>
                </div>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
