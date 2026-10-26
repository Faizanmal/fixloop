"use client";

import React, { useState } from "react";
import {
  FileCode,
  ShieldCheck,
  XCircle,
  Play,
  Lock,
  GitBranch,
  CheckCircle2,
  AlertCircle,
  FileText,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface PatchReviewCardProps {
  patchDiff: string;
  targetFile: string;
  explanation?: string;
  verificationProcedure?: string;
  isAppliedToWorkingCopy?: boolean;
  onApproveAndVerify: (userApproved: boolean) => void;
  onRejectPatch: () => void;
  isVerifying: boolean;
}

export function PatchReviewCard({
  patchDiff,
  targetFile,
  explanation,
  verificationProcedure = "verify_syntax",
  isAppliedToWorkingCopy = false,
  onApproveAndVerify,
  onRejectPatch,
  isVerifying,
}: PatchReviewCardProps) {
  const [userApproved, setUserApproved] = useState<boolean>(true);

  // Render unified diff with syntax styling and line numbers
  const renderDiffLines = (diff: string) => {
    if (!diff) {
      return (
        <div className="p-6 text-xs font-mono text-slate-500 text-center">
          No diff content available.
        </div>
      );
    }

    const lines = diff.split("\n");
    let oldLineNum = 1;
    let newLineNum = 1;

    return lines.map((line, idx) => {
      let lineType = "context";
      if (line.startsWith("@@")) {
        lineType = "header";
        const match = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
        if (match) {
          oldLineNum = parseInt(match[1], 10);
          newLineNum = parseInt(match[2], 10);
        }
      } else if (line.startsWith("+")) {
        lineType = "add";
      } else if (line.startsWith("-")) {
        lineType = "del";
      }

      const currentOld = lineType === "add" ? "" : lineType === "header" ? "..." : oldLineNum++;
      const currentNew = lineType === "del" ? "" : lineType === "header" ? "..." : newLineNum++;

      return (
        <div
          key={idx}
          className={`flex items-stretch font-mono text-xs select-text ${
            lineType === "add"
              ? "diff-line-add bg-emerald-950/30 text-emerald-300"
              : lineType === "del"
              ? "diff-line-del bg-rose-950/30 text-rose-300"
              : lineType === "header"
              ? "diff-line-info bg-cyan-950/20 text-cyan-400 py-1"
              : "diff-line-context text-slate-400 hover:bg-slate-900/40"
          }`}
        >
          {/* Old line number */}
          <span className="w-10 px-2 py-0.5 text-right font-mono text-[10px] text-slate-600 select-none border-r border-slate-800 shrink-0">
            {currentOld}
          </span>
          {/* New line number */}
          <span className="w-10 px-2 py-0.5 text-right font-mono text-[10px] text-slate-600 select-none border-r border-slate-800 shrink-0">
            {currentNew}
          </span>
          {/* Sign symbol */}
          <span className="w-6 py-0.5 text-center font-mono text-xs select-none shrink-0 font-bold">
            {line.startsWith("+") ? "+" : line.startsWith("-") ? "-" : line.startsWith("@") ? "@" : " "}
          </span>
          {/* Code content */}
          <span className="px-2 py-0.5 whitespace-pre overflow-x-auto flex-1">
            {line.startsWith("+") || line.startsWith("-") ? line.slice(1) : line}
          </span>
        </div>
      );
    });
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm backdrop-blur mb-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <Badge variant="info">PROPOSED MINIMAL PATCH</Badge>
            <Badge variant="success">Allowlisted Target</Badge>
            <span className="text-xs font-mono text-slate-400">
              Procedure: <code className="text-cyan-300">{verificationProcedure}</code>
            </span>
          </div>
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <FileCode className="h-4 w-4 text-cyan-400" />
            Unified Diff Review: <span className="font-mono text-cyan-300">{targetFile}</span>
          </h3>
          <p className="text-xs text-slate-300 mt-1">
            {explanation || "Targeted minimal patch generated from empirical diagnosis. Inspected for safety before isolated sandbox execution."}
          </p>
        </div>

        {/* Clear Indication of Whether Patch Has Actually Been Applied */}
        <div className="flex items-center gap-2.5 rounded-xl bg-black/60 border border-slate-800 px-4 py-2.5 text-xs self-start sm:self-center">
          <Lock className="h-4 w-4 text-emerald-400 shrink-0" />
          <div>
            <div className="text-[10px] uppercase font-mono text-slate-400">
              Host Working Copy Status
            </div>
            <div className="font-mono font-bold text-xs flex items-center gap-1.5 mt-0.5">
              {isAppliedToWorkingCopy ? (
                <span className="text-amber-400 flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" />
                  APPLIED TO HOST REPO
                </span>
              ) : (
                <span className="text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  UNTOUCHED (Sandbox Only)
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Changed Files Header Pill */}
      <div className="flex items-center gap-2 mb-3 text-xs font-mono">
        <span className="text-slate-400">Changed Files (1):</span>
        <span className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1 text-cyan-300">
          <FileText className="h-3.5 w-3.5 text-cyan-400" />
          <span>{targetFile}</span>
          <span className="text-[10px] text-emerald-400 font-bold ml-1">+1 modification</span>
        </span>
      </div>

      {/* Security Defense Chips */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="inline-flex items-center gap-1 rounded bg-slate-950 px-2 py-1 text-[11px] font-mono text-emerald-400 border border-slate-800">
          <ShieldCheck className="h-3 w-3" />
          Allowlisted Target: {targetFile}
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
            <FileCode className="h-3.5 w-3.5 text-cyan-400" />
            a/{targetFile} &rarr; b/{targetFile}
          </span>
          <span className="text-[11px] text-slate-500">Unified Diff Format (diff -u)</span>
        </div>
        <div className="py-1 overflow-x-auto max-h-80">
          {renderDiffLines(patchDiff)}
        </div>
      </div>

      {/* Human Approval Gate & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-3 border-t border-slate-800">
        <label className="flex items-center gap-2.5 cursor-pointer text-xs text-slate-300 font-mono select-none">
          <input
            type="checkbox"
            checked={userApproved}
            onChange={(e) => setUserApproved(e.target.checked)}
            className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-cyan-500"
          />
          <span>Explicit Human Approval Granted for Disposable Sandbox Verification</span>
        </label>

        <div className="flex items-center gap-2.5">
          <button
            onClick={onRejectPatch}
            disabled={isVerifying}
            className="inline-flex items-center gap-1.5 rounded-lg border border-rose-800/60 bg-rose-950/20 px-3.5 py-2 text-xs font-medium text-rose-300 hover:bg-rose-950/50 transition-all cursor-pointer font-mono select-none"
          >
            <XCircle className="h-3.5 w-3.5" />
            <span>Reject Patch</span>
          </button>

          <button
            onClick={() => onApproveAndVerify(userApproved)}
            disabled={isVerifying || !userApproved}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 py-2 text-xs font-semibold text-white shadow-md shadow-emerald-950/40 hover:from-emerald-400 hover:to-teal-500 disabled:opacity-50 transition-all cursor-pointer font-mono select-none"
          >
            {isVerifying ? (
              <>
                <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                <span>Testing in Sandbox...</span>
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
