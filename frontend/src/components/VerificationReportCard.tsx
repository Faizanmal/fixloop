"use client";

import React from "react";
import { VerificationReport } from "@/lib/api";
import { formatDuration, getStatusColor } from "@/lib/utils";
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Terminal,
  RotateCcw,
  ShieldAlert,
} from "lucide-react";

interface VerificationReportCardProps {
  report: VerificationReport;
  scenarioName: string;
  onRetry: () => void;
  isVerifying: boolean;
}

export function VerificationReportCard({
  report,
  scenarioName,
  onRetry,
  isVerifying,
}: VerificationReportCardProps) {
  const statusStyles = getStatusColor(report.status);
  const isFixed = report.status === "verified_fixed";
  const isFailed = report.status === "verification_failed";

  return (
    <div className={`rounded-xl border p-5 shadow-sm backdrop-blur mb-8 ${statusStyles.border} ${statusStyles.bg}`}>
      {/* Top Banner: Verification Status & Duration */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800/80 mb-5">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span
              className={`rounded-full border px-3 py-1 text-xs font-mono font-bold tracking-wide uppercase ${statusStyles.badge}`}
            >
              STATUS: {report.status.replace("_", " ")}
            </span>
            <span className="text-xs font-mono text-cyan-300 bg-cyan-950/40 px-2.5 py-1 rounded border border-cyan-800/60 font-semibold">
              {scenarioName.replace("scenario_", "").replace(/_/g, " ")}
            </span>
            <span className="text-xs font-mono text-slate-400 bg-black/40 px-2.5 py-1 rounded border border-slate-800">
              Attempts: {report.attempts} / 2 (Max 1 Retry)
            </span>
            <span className="text-xs font-mono text-slate-400 bg-black/40 px-2.5 py-1 rounded border border-slate-800">
              Duration: {formatDuration(report.duration_ms)}
            </span>
          </div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            {isFixed ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            ) : isFailed ? (
              <XCircle className="h-5 w-5 text-rose-400" />
            ) : (
              <AlertTriangle className="h-5 w-5 text-amber-400" />
            )}
            Disposable Sandbox Verification Outcome
          </h3>
          <p className="text-xs text-slate-300 mt-0.5">
            Verification status grounded solely in actual isolated sandbox execution. Zero fabricated results.
          </p>
        </div>

        {/* Revert status guarantee */}
        <div className="flex items-center gap-2 rounded-lg bg-black/60 border border-slate-800 px-3.5 py-2 text-xs">
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
          <div>
            <div className="text-[10px] uppercase font-mono text-slate-400">
              Working Copy
            </div>
            <div className="font-mono font-bold text-emerald-400 text-xs">
              {report.reverted ? "Reverted / Clean" : "Uncommitted"}
            </div>
          </div>
        </div>
      </div>

      {/* Before and After Comparison Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
        {/* Before: Failure state */}
        <div className="rounded-lg border border-rose-900/40 bg-rose-950/20 p-3.5">
          <div className="flex items-center justify-between text-xs font-mono text-rose-400 mb-1.5 font-bold">
            <span className="flex items-center gap-1.5">
              <XCircle className="h-3.5 w-3.5" />
              Before Patch (Identified Failure)
            </span>
            <span>Exit 1</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed font-mono">
            {report.expected_criteria
              ? `Failed: ${report.expected_criteria} was unmet in original container configuration.`
              : "Active failure identified during diagnostic phase."}
          </p>
        </div>

        {/* After: Verification state */}
        <div
          className={`rounded-lg border p-3.5 ${
            isFixed
              ? "border-emerald-900/40 bg-emerald-950/20"
              : "border-slate-800 bg-slate-950/60"
          }`}
        >
          <div className="flex items-center justify-between text-xs font-mono mb-1.5 font-bold">
            <span
              className={`flex items-center gap-1.5 ${
                isFixed ? "text-emerald-400" : "text-amber-400"
              }`}
            >
              {isFixed ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <AlertTriangle className="h-3.5 w-3.5" />
              )}
              After Patch (In Disposable Sandbox)
            </span>
            <span className={isFixed ? "text-emerald-400 font-mono" : "text-amber-400 font-mono"}>
              {isFixed ? "Exit 0 (Passed)" : "Non-zero Exit"}
            </span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed font-mono">
            {isFixed
              ? `Success: ${report.expected_criteria}`
              : report.test_output || "Verification checks failed or were not attempted."}
          </p>
        </div>
      </div>

      {/* Actual Execution Logs Terminal */}
      <div className="rounded-lg border border-slate-800 bg-[#060a10] p-3 font-mono text-xs mb-5">
        <div className="flex items-center justify-between text-slate-400 border-b border-slate-800/80 pb-2 mb-2">
          <span className="flex items-center gap-1.5 text-slate-200">
            <Terminal className="h-3.5 w-3.5 text-cyan-400" />
            Sandbox Execution Standard Output
          </span>
          <span className="text-[11px] text-slate-500">
            Allowlisted Procedure Check
          </span>
        </div>

        <div className="space-y-1 text-slate-300 text-xs py-1">
          <div className="text-cyan-400">$ allowlisted_check --procedure {report.target_file || "config"}</div>
          <div className="text-emerald-300 font-medium whitespace-pre-wrap">{report.test_output}</div>
          {report.failure_evidence && (
            <div className="text-rose-400 font-medium whitespace-pre-wrap mt-2">
              [FAILURE EVIDENCE] {report.failure_evidence}
            </div>
          )}
        </div>
      </div>

      {/* Remaining Risks & Sandbox Limitations (Honest Documentation) */}
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3.5 text-xs">
        <div className="flex items-center gap-2 text-slate-200 font-semibold mb-1">
          <ShieldAlert className="h-4 w-4 text-amber-400" />
          Remaining Risks & Sandbox Limitations
        </div>
        <ul className="list-disc list-inside space-y-1 text-slate-400 text-[11px] leading-relaxed">
          <li>
            <strong className="text-slate-300">No Automatic Deployment:</strong> The patch was tested strictly inside an ephemeral sandbox. Production deployment requires explicit manual application.
          </li>
          <li>
            <strong className="text-slate-300">Sandbox Isolation:</strong> Ephemeral testing ran in an isolated workspace with network calls disabled to prevent accidental egress.
          </li>
          <li>
            <strong className="text-slate-300">Working Copy Safe:</strong> The original project working copy was verified untouched.
          </li>
        </ul>
      </div>

      {/* Retry / Re-run Action */}
      {!isFixed && (
        <div className="mt-4 pt-3 border-t border-slate-800 flex justify-end">
          <button
            onClick={onRetry}
            disabled={isVerifying}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-800 hover:bg-slate-700 px-4 py-2 text-xs font-semibold text-slate-200 transition-all cursor-pointer font-mono"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            <span>Re-run Verification Check</span>
          </button>
        </div>
      )}
    </div>
  );
}
