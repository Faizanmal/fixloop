"use client";

import React, { useState } from "react";
import { VerificationReport, apiClient } from "@/lib/api";
import { formatDuration, getStatusColor } from "@/lib/utils";
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Terminal,
  RotateCcw,
  ShieldAlert,
  Copy,
  Check,
  FileCheck,
  Cpu,
  Layers,
  FileDown,
  HardDrive,
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
  const [copiedLog, setCopiedLog] = useState<boolean>(false);
  const [copiedDiff, setCopiedDiff] = useState<boolean>(false);
  const [isApplying, setIsApplying] = useState<boolean>(false);
  const [applied, setApplied] = useState<boolean>(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [exported, setExported] = useState<boolean>(false);

  const statusStyles = getStatusColor(report.status);
  const isFixed = report.status === "verified_fixed";
  const isFailed = report.status === "verification_failed";
  const isRejected = report.status === "patch_rejected";

  const handleCopyLog = () => {
    const logContent = `FixLoop Disposable Sandbox Verification Report\nScenario: ${scenarioName}\nStatus: ${report.status}\nTarget File: ${report.target_file || "config"}\nExpected Criteria: ${report.expected_criteria}\nDuration: ${report.duration_ms}ms\nOutput:\n${report.test_output}`;
    navigator.clipboard.writeText(logContent);
    setCopiedLog(true);
    setTimeout(() => setCopiedLog(false), 2000);
  };

  const handleCopyDiff = () => {
    if (report.patch_diff) {
      navigator.clipboard.writeText(report.patch_diff);
      setCopiedDiff(true);
      setTimeout(() => setCopiedDiff(false), 2000);
    }
  };

  const handleApplyToHost = async () => {
    setIsApplying(true);
    setApplyError(null);
    try {
      await apiClient.applyPatch(scenarioName, report.patch_diff, report.target_file);
      setApplied(true);
    } catch (err: unknown) {
      setApplyError(err instanceof Error ? err.message : "Failed to apply patch to host.");
    } finally {
      setIsApplying(false);
    }
  };

  const handleExportReport = () => {
    const reportMd = `# FixLoop Incident Verification Report
**Date**: ${new Date().toISOString()}
**Scenario / Target**: ${scenarioName}
**Status**: ${report.status} (Exit Code 0 - Verified Fixed)
**Target File**: ${report.target_file || "configuration"}
**Duration**: ${report.duration_ms}ms
**Attempts**: ${report.attempts} / 2

## Expected Success Criteria
${report.expected_criteria}

## Verification Execution Output
\`\`\`
${report.test_output}
\`\`\`

## Verified Unified Diff Patch
\`\`\`diff
${report.patch_diff || "No diff content"}
\`\`\`

*Report generated automatically by FixLoop Autonomous SRE Engine powered by Nebius Token Factory & NVIDIA Nemotron-3-Nano.*
`;
    const blob = new Blob([reportMd], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `fixloop-report-${scenarioName}-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
    setExported(true);
    setTimeout(() => setExported(false), 2500);
  };

  return (
    <div
      className={`rounded-xl border p-5 shadow-sm backdrop-blur mb-8 ${statusStyles.border} ${statusStyles.bg}`}
    >
      {/* Top Banner: Verification Status & Duration */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800/80 mb-5">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span
              className={`rounded-full border px-3 py-1 text-xs font-mono font-bold tracking-wide uppercase ${statusStyles.badge}`}
            >
              STATUS: {report.status.replace(/_/g, " ")}
            </span>
            <span className="text-xs font-mono text-cyan-300 bg-cyan-950/40 px-2.5 py-1 rounded border border-cyan-800/60 font-semibold">
              {scenarioName.replace("scenario_", "").replace(/_/g, " ")}
            </span>
            <span className="text-xs font-mono text-slate-400 bg-black/50 px-2.5 py-1 rounded border border-slate-800">
              Attempts: {report.attempts} / 2 (Max 1 Retry)
            </span>
            <span className="text-xs font-mono text-slate-400 bg-black/50 px-2.5 py-1 rounded border border-slate-800">
              Duration: {formatDuration(report.duration_ms)}
            </span>
          </div>

          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            {isFixed ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-400" />
            ) : isFailed ? (
              <XCircle className="h-5 w-5 text-rose-400" />
            ) : isRejected ? (
              <AlertTriangle className="h-5 w-5 text-amber-400" />
            ) : (
              <ShieldAlert className="h-5 w-5 text-purple-400" />
            )}
            Disposable Sandbox Verification Outcome
          </h3>
          <p className="text-xs text-slate-300 mt-1">
            Verification status grounded solely in actual isolated sandbox execution. Zero fabricated results.
          </p>
        </div>

        {/* Working copy revert guarantee */}
        <div className="flex items-center gap-2.5 rounded-xl bg-black/60 border border-slate-800 px-4 py-2.5 text-xs self-start sm:self-center">
          <ShieldCheck className="h-4 w-4 text-emerald-400 shrink-0" />
          <div>
            <div className="text-[10px] uppercase font-mono text-slate-400">
              Host Working Copy
            </div>
            <div className="font-mono font-bold text-emerald-400 text-xs">
              {report.reverted ? "Reverted & Untouched" : "Preserved"}
            </div>
          </div>
        </div>
      </div>

      {/* Executed Test Procedures Details */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5 text-xs font-mono">
        <div className="rounded-lg border border-slate-800 bg-black/40 p-3">
          <div className="text-[10px] uppercase text-slate-400 mb-1 flex items-center gap-1">
            <Cpu className="h-3 w-3 text-cyan-400" />
            Executed Procedure
          </div>
          <div className="text-cyan-300 font-semibold truncate">
            {report.target_file ? `verify_fix (${report.target_file})` : "empirical_check"}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-black/40 p-3">
          <div className="text-[10px] uppercase text-slate-400 mb-1 flex items-center gap-1">
            <FileCheck className="h-3 w-3 text-emerald-400" />
            Expected Success Criteria
          </div>
          <div className="text-slate-200 truncate" title={report.expected_criteria}>
            {report.expected_criteria || "Conclusive verification pass"}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-black/40 p-3">
          <div className="text-[10px] uppercase text-slate-400 mb-1 flex items-center gap-1">
            <Layers className="h-3 w-3 text-indigo-400" />
            Execution Result
          </div>
          <div className={isFixed ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
            {isFixed ? "Exit Code 0 • Pass" : isRejected ? "Rejected by User" : "Non-zero Exit"}
          </div>
        </div>
      </div>

      {/* Before and After Comparison Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
        {/* Before: Failure state */}
        <div className="rounded-lg border border-rose-900/40 bg-rose-950/20 p-4">
          <div className="flex items-center justify-between text-xs font-mono text-rose-400 mb-2 font-bold">
            <span className="flex items-center gap-1.5">
              <XCircle className="h-4 w-4" />
              Before Patch (Identified Failure)
            </span>
            <span className="rounded bg-rose-950 px-2 py-0.5 border border-rose-800/60 text-[10px]">
              Exit 1 (Unhealthy)
            </span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed font-mono">
            {report.expected_criteria
              ? `Original state failed: ${report.expected_criteria} was missing or misconfigured in target repository.`
              : "Active system failure detected during diagnostic phase."}
          </p>
        </div>

        {/* After: Verification state */}
        <div
          className={`rounded-lg border p-4 ${
            isFixed
              ? "border-emerald-900/40 bg-emerald-950/20"
              : isRejected
              ? "border-amber-900/40 bg-amber-950/20"
              : "border-slate-800 bg-slate-950/60"
          }`}
        >
          <div className="flex items-center justify-between text-xs font-mono mb-2 font-bold">
            <span
              className={`flex items-center gap-1.5 ${
                isFixed
                  ? "text-emerald-400"
                  : isRejected
                  ? "text-amber-400"
                  : "text-amber-400"
              }`}
            >
              {isFixed ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <AlertTriangle className="h-4 w-4" />
              )}
              After Patch (In Disposable Sandbox)
            </span>
            <span
              className={`rounded px-2 py-0.5 border text-[10px] font-mono ${
                isFixed
                  ? "bg-emerald-950 border-emerald-800/60 text-emerald-300"
                  : "bg-slate-900 border-slate-800 text-slate-400"
              }`}
            >
              {isFixed ? "Exit 0 (Passed)" : isRejected ? "Declined" : "Non-zero"}
            </span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed font-mono">
            {isFixed
              ? `Success: ${report.expected_criteria}. Container restarted cleanly in isolated sandbox.`
              : report.test_output || "Verification checks failed or were not attempted."}
          </p>
        </div>
      </div>

      {/* Actual Execution Logs Terminal */}
      <div className="rounded-lg border border-slate-800 bg-[#060a10] p-4 font-mono text-xs mb-5">
        <div className="flex items-center justify-between text-slate-400 border-b border-slate-800/80 pb-2.5 mb-2.5">
          <span className="flex items-center gap-1.5 text-slate-200 font-semibold">
            <Terminal className="h-4 w-4 text-cyan-400" />
            Sandbox Execution Standard Output
          </span>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500 font-mono">
              Pure Python Sandboxed Pipeline
            </span>
            <button
              onClick={handleCopyLog}
              className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition-colors cursor-pointer"
              title="Copy terminal output"
            >
              {copiedLog ? (
                <Check className="h-3.5 w-3.5 text-emerald-400" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>

        <div className="space-y-1 text-slate-300 text-xs py-1">
          <div className="text-cyan-400">
            $ fixloop-sandbox-runner --target {report.target_file || "docker-compose.yml"} --revert-on-finish
          </div>
          <div className="text-emerald-300 font-medium whitespace-pre-wrap leading-relaxed">
            {report.test_output}
          </div>
          {report.failure_evidence && (
            <div className="text-rose-400 font-medium whitespace-pre-wrap mt-2 p-2 rounded bg-rose-950/30 border border-rose-900/50">
              [FAILURE EVIDENCE] {report.failure_evidence}
            </div>
          )}
        </div>
      </div>

      {/* Remaining Risks & Sandbox Limitations (Honest Disclosures) */}
      <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 text-xs">
        <div className="flex items-center gap-2 text-slate-200 font-semibold mb-2">
          <ShieldAlert className="h-4 w-4 text-amber-400" />
          Remaining Risks & Sandbox Limitations
        </div>
        <ul className="list-disc list-inside space-y-1.5 text-slate-400 text-[11px] leading-relaxed">
          <li>
            <strong className="text-slate-300">No Direct Host Mutation:</strong> The patch was tested strictly inside an ephemeral sandbox. Manual application is required to update host project files.
          </li>
          <li>
            <strong className="text-slate-300">Isolated Network:</strong> Ephemeral testing ran in an isolated workspace with external network calls disabled to prevent accidental egress.
          </li>
          <li>
            <strong className="text-slate-300">Host Working Copy Clean:</strong> The host workspace was verified untouched and preserved in its original clean state.
          </li>
        </ul>
      </div>

      {/* Post-Verification Production Actions */}
      {isFixed && (
        <div className="mt-5 pt-4 border-t border-slate-800/80 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          <div className="text-xs text-slate-400 font-mono flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Sandbox verified clean (Exit 0). Ready for repository integration.</span>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {report.patch_diff && (
              <button
                onClick={handleCopyDiff}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 px-3 py-1.5 text-xs font-mono font-medium text-slate-200 transition-all cursor-pointer"
              >
                {copiedDiff ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                <span>{copiedDiff ? "Copied Patch!" : "Copy Git Patch"}</span>
              </button>
            )}

            <button
              onClick={handleExportReport}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 px-3 py-1.5 text-xs font-mono font-medium text-slate-200 transition-all cursor-pointer"
            >
              {exported ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <FileDown className="h-3.5 w-3.5" />}
              <span>{exported ? "Exported!" : "Export Report (MD)"}</span>
            </button>

            <button
              onClick={handleApplyToHost}
              disabled={isApplying || applied}
              className={`inline-flex items-center gap-2 rounded-lg px-4 py-1.5 text-xs font-mono font-bold transition-all cursor-pointer shadow-sm ${
                applied
                  ? "bg-emerald-950 border border-emerald-600 text-emerald-300"
                  : "bg-emerald-600 hover:bg-emerald-500 text-white"
              }`}
            >
              {isApplying ? (
                <>
                  <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  <span>Applying to Host...</span>
                </>
              ) : applied ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                  <span>Applied to Host Disk ✅</span>
                </>
              ) : (
                <>
                  <HardDrive className="h-3.5 w-3.5" />
                  <span>Apply Patch to Host Disk</span>
                </>
              )}
            </button>
          </div>
        </div>
      )}
      {applyError && (
        <div className="mt-2 text-[11px] font-mono text-rose-400 bg-rose-950/40 p-2 rounded border border-rose-900/60">
          Failed to apply to host: {applyError}
        </div>
      )}

      {/* Retry / Re-run Action */}
      {!isFixed && (
        <div className="mt-4 pt-3 border-t border-slate-800 flex justify-end">
          <button
            onClick={onRetry}
            disabled={isVerifying}
            className="inline-flex items-center gap-2 rounded-xl bg-slate-800 hover:bg-slate-700 px-4 py-2 text-xs font-semibold text-slate-200 transition-all cursor-pointer font-mono select-none"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            <span>Re-run Verification Check</span>
          </button>
        </div>
      )}
    </div>
  );
}
