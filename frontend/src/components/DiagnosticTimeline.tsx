"use client";

import React from "react";
import { DiagnoseResponse } from "@/lib/api";
import {
  Clock,
  Terminal,
  Activity,
  Check,
} from "lucide-react";

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
  const steps = [
    {
      id: 1,
      name: "Evidence Ingestion",
      desc: "Logs & environment parsed without leaking secrets",
      completed: !!diagnosis || isInvestigating,
      active: isInvestigating && !diagnosis,
    },
    {
      id: 2,
      name: "Configuration Audit",
      desc: "Docker Compose & container inspect analyzed",
      completed: !!diagnosis,
      active: false,
    },
    {
      id: 3,
      name: "Diagnostic Probing",
      desc: "Allowlisted HTTP/TCP probes executed",
      completed: !!diagnosis && (diagnosis.audit_log?.probes_executed?.length ?? 0) > 0,
      active: false,
    },
    {
      id: 4,
      name: "Hypothesis Ranking",
      desc: "Evidence-weighted calibrated confidence",
      completed: !!diagnosis,
      active: false,
    },
    {
      id: 5,
      name: "Sandbox Verification",
      desc: "Tested in isolated disposable sandbox",
      completed: hasPatchVerified,
      active: false,
    },
  ];

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 mb-8 backdrop-blur">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300 flex items-center gap-2">
          <Activity className="h-4 w-4 text-cyan-400" />
          Diagnostic Pipeline Sequence
        </h3>
        {diagnosis?.audit_log?.stop_reason && (
          <span className="text-xs font-mono text-cyan-400 bg-cyan-950/40 border border-cyan-800/60 px-2 py-0.5 rounded">
            Stop: {diagnosis.audit_log.stop_reason}
          </span>
        )}
      </div>

      {/* Stepper progress */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3 mb-4">
        {steps.map((st) => (
          <div
            key={st.id}
            className={`flex flex-col p-3 rounded-lg border transition-all ${
              st.completed
                ? "border-emerald-800/60 bg-emerald-950/20 text-emerald-300"
                : st.active
                ? "border-cyan-500 bg-cyan-950/30 text-cyan-200 animate-pulse"
                : "border-slate-800 bg-slate-900/60 text-slate-500"
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-mono font-bold">Step {st.id}</span>
              {st.completed ? (
                <Check className="h-4 w-4 text-emerald-400" />
              ) : st.active ? (
                <div className="h-2 w-2 rounded-full bg-cyan-400 animate-ping" />
              ) : (
                <Clock className="h-3.5 w-3.5 text-slate-600" />
              )}
            </div>
            <span className="text-xs font-semibold text-slate-200">{st.name}</span>
            <span className="text-[10px] text-slate-400 leading-tight mt-1 line-clamp-2">
              {st.desc}
            </span>
          </div>
        ))}
      </div>

      {/* Audit Log Terminal Preview if available */}
      {diagnosis?.audit_log && (
        <div className="mt-3 rounded-lg border border-slate-800 bg-black/50 p-3 font-mono text-xs">
          <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-1.5 mb-2">
            <span className="flex items-center gap-1.5 text-slate-300">
              <Terminal className="h-3.5 w-3.5 text-cyan-400" />
              Audit Log: Executed Actions & Observations
            </span>
            <span className="text-[10px] text-slate-500">
              {diagnosis.audit_log.observations.length} observations •{" "}
              {diagnosis.audit_log.probes_executed.length} active probes
            </span>
          </div>
          <div className="space-y-1 max-h-36 overflow-y-auto text-slate-300 text-[11px]">
            {diagnosis.audit_log.probes_executed.map((probe, i) => (
              <div key={`p-${i}`} className="flex items-start gap-2 text-cyan-300">
                <span className="text-cyan-500 font-bold">[PROBE]</span>
                <span>{probe}</span>
              </div>
            ))}
            {diagnosis.audit_log.observations.map((obs, i) => (
              <div key={`o-${i}`} className="flex items-start gap-2 text-slate-300">
                <span className="text-slate-500 font-bold">[FACT]</span>
                <span>{obs}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
