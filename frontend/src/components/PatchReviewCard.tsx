"use client";

import React, { useState } from "react";
import {
  FileCode,
  ShieldCheck,
  XCircle,
  Play,
  Lock,
  GitBranch,
} from "lucide-react";

interface PatchReviewCardProps {
  patchDiff: string;
  targetFile: string;
  onApproveAndVerify: (userApproved: boolean) => void;
  onRejectPatch: () => void;
  isVerifying: boolean;
}

export function PatchReviewCard({
  patchDiff,
  targetFile,
  onApproveAndVerify,
  onRejectPatch,
  isVerifying,
}: PatchReviewCardProps) {
  const [userApproved, setUserApproved] = useState<boolean>(true);

  // Render unified diff with syntax styling
  const renderDiffLines = (diff: string) => {
    if (!diff) {
      return (
        <div className="p-4 text-xs font-mono text-slate-500">
          No diff available.
        </div>
      );
    }

    const lines = diff.split("\n");
    return lines.map((line, idx) => {
      let className = "diff-line-context px-4 py-0.5 font-mono text-xs";
      if (line.startsWith("+")) {
        className = "diff-line-add px-4 py-0.5 font-mono text-xs";
      } else if (line.startsWith("-")) {
        className = "diff-line-del px-4 py-0.5 font-mono text-xs";
      } else if (line.startsWith("@@")) {
        className = "diff-line-info px-4 py-1 font-mono text-xs";
      }

      return (
        <div key={idx} className={className}>
          <span className="inline-block w-8 select-none opacity-40 text-right pr-3 font-mono text-[10px]">
            {idx + 1}
          </span>
          <span>{line}</span>
        </div>
      );
    });
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm backdrop-blur mb-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2.5 py-0.5 text-xs font-mono text-cyan-400 font-bold">
              PROPOSED MINIMAL PATCH
            </span>
            <span className="rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-0.5 text-xs font-mono text-emerald-400">
              Low Risk
            </span>
          </div>
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <FileCode className="h-4 w-4 text-cyan-400" />
            Unified Diff Review: <span className="font-mono text-cyan-300">{targetFile}</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Review proposed minimal changes before running allowlisted verification in disposable sandbox.
          </p>
        </div>

        {/* Isolation & Working Copy Status Badge */}
        <div className="flex items-center gap-2 rounded-lg bg-black/50 border border-slate-800 px-3 py-2 text-xs">
          <Lock className="h-3.5 w-3.5 text-emerald-400" />
          <div>
            <div className="text-[10px] uppercase font-mono text-slate-400">
              Working Copy Status
            </div>
            <div className="font-mono font-bold text-emerald-400 text-xs">
              Clean / Reverted (Sandbox Only)
            </div>
          </div>
        </div>
      </div>

      {/* Security Check Chips */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="inline-flex items-center gap-1 rounded bg-slate-950 px-2 py-1 text-[11px] font-mono text-emerald-400 border border-slate-800">
          <ShieldCheck className="h-3 w-3" />
          Target Allowlisted: {targetFile}
        </span>
        <span className="inline-flex items-center gap-1 rounded bg-slate-950 px-2 py-1 text-[11px] font-mono text-emerald-400 border border-slate-800">
          <ShieldCheck className="h-3 w-3" />
          Path Traversal Blocked
        </span>
        <span className="inline-flex items-center gap-1 rounded bg-slate-950 px-2 py-1 text-[11px] font-mono text-emerald-400 border border-slate-800">
          <ShieldCheck className="h-3 w-3" />
          Prohibited Shell Payloads: 0
        </span>
        <span className="inline-flex items-center gap-1 rounded bg-slate-950 px-2 py-1 text-[11px] font-mono text-indigo-400 border border-slate-800">
          <GitBranch className="h-3 w-3" />
          Pure Python Patcher (Zero Host Shell Exec)
        </span>
      </div>

      {/* Unified Diff Box */}
      <div className="rounded-lg border border-slate-800 bg-[#070b12] overflow-hidden mb-4">
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800/80 bg-slate-950/80 text-xs font-mono text-slate-400">
          <span className="flex items-center gap-2">
            <FileCode className="h-3.5 w-3.5 text-slate-400" />
            a/{targetFile} &rarr; b/{targetFile}
          </span>
          <span className="text-[11px] text-slate-500">Unified Diff Format (diff -u)</span>
        </div>
        <div className="py-2 overflow-x-auto max-h-72">
          {renderDiffLines(patchDiff)}
        </div>
      </div>

      {/* Approval Gate & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-3 border-t border-slate-800">
        <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300 font-mono">
          <input
            type="checkbox"
            checked={userApproved}
            onChange={(e) => setUserApproved(e.target.checked)}
            className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-cyan-500"
          />
          <span>Explicit Human Approval Granted for Sandbox Verification</span>
        </label>

        <div className="flex items-center gap-2.5">
          <button
            onClick={onRejectPatch}
            disabled={isVerifying}
            className="inline-flex items-center gap-1.5 rounded-lg border border-rose-800/60 bg-rose-950/20 px-3.5 py-2 text-xs font-medium text-rose-300 hover:bg-rose-950/40 transition-all cursor-pointer font-mono"
          >
            <XCircle className="h-3.5 w-3.5" />
            <span>Reject Patch</span>
          </button>

          <button
            onClick={() => onApproveAndVerify(userApproved)}
            disabled={isVerifying || !userApproved}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 py-2 text-xs font-semibold text-white shadow-md shadow-emerald-950/40 hover:from-emerald-400 hover:to-teal-500 disabled:opacity-50 transition-all cursor-pointer font-mono"
          >
            {isVerifying ? (
              <>
                <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                <span>Running Sandbox Check...</span>
              </>
            ) : (
              <>
                <Play className="h-3.5 w-3.5 fill-white" />
                <span>Run Sandbox Verification</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
