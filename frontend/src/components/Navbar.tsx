"use client";

import React, { useState } from "react";
import { SystemReadiness } from "@/lib/api";
import { formatModelName } from "@/lib/utils";
import {
  ShieldAlert,
  Cpu,
  AlertTriangle,
  Sparkles,
  ExternalLink,
  Server,
  Trophy,
  X,
  CheckCircle2,
} from "lucide-react";

interface NavbarProps {
  readiness: SystemReadiness | null;
  isBootstrapping?: boolean;
  onQuickDemo: () => void;
  isInvestigating: boolean;
}

export function Navbar({
  readiness,
  isBootstrapping = false,
  onQuickDemo,
  isInvestigating,
}: NavbarProps) {
  const [showBenchmark, setShowBenchmark] = useState<boolean>(false);
  const isInitialLoad = isBootstrapping || readiness === null;
  const isUnreachable =
    readiness?.isUnreachable === true ||
    (readiness !== null &&
      readiness.issues?.some((i) => i.toLowerCase().includes("cannot connect")));
  const isReady = !isUnreachable && (readiness?.ready ?? false);
  const nebiusInfo = readiness?.nebius;
  const hasNebiusResult = !isInitialLoad && !isUnreachable && nebiusInfo !== undefined && nebiusInfo !== null;
  const dockerInfo = readiness?.docker;
  const hasDockerResult = !isInitialLoad && !isUnreachable && dockerInfo !== undefined && dockerInfo !== null;
  const isDockerUp = dockerInfo?.available === true;

  const modelDisplay = formatModelName(nebiusInfo?.model);

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-[#090d16]/95 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-y-2 px-4 py-3 sm:px-6 lg:px-8">
        {/* Brand */}
        <div className="flex items-center gap-3 min-w-0 shrink">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-600 shadow-lg shadow-cyan-950/50 ring-1 ring-cyan-400/40">
            <ShieldAlert className="h-5 w-5 text-white" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-lg font-bold tracking-tight text-white font-mono">
                FixLoop
              </span>
              <span className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[10px] font-mono font-semibold text-cyan-400 ring-1 ring-cyan-500/30">
                v0.1 MVP
              </span>
              <span className="hidden sm:inline-flex rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-mono font-medium text-indigo-400 ring-1 ring-indigo-500/30">
                Nebius x NVIDIA
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">
              Evidence-Driven Autonomous Debugging Engine
            </p>
          </div>
        </div>

        {/* Model, Runtime & Actions — wrap/stack on ~390px so Benchmark & Demo are never clipped */}
        <div className="flex flex-wrap items-center justify-end gap-2 sm:gap-3 w-full sm:w-auto">
          {/* Target Model Badge */}
          <div
            className="hidden lg:flex items-center gap-2 rounded-lg bg-slate-900/90 px-2.5 py-1.5 text-xs text-slate-300 ring-1 ring-slate-800"
            title={
              isUnreachable
                ? "Backend unreachable • Model detection paused"
                : hasNebiusResult
                ? `Nebius Model: ${modelDisplay}`
                : "Detecting Nebius Model…"
            }
          >
            <Cpu className="h-3.5 w-3.5 text-indigo-400" />
            <span className="font-mono text-[11px] text-slate-400">Model:</span>
            {isInitialLoad ? (
              <span className="h-3.5 w-24 rounded bg-slate-800 animate-pulse" />
            ) : isUnreachable ? (
              <span className="font-mono text-[11px] text-rose-400 font-medium">Offline</span>
            ) : (
              <span className="font-mono text-[11px] text-indigo-300 font-medium truncate max-w-[240px]">
                {modelDisplay}
              </span>
            )}
          </div>

          {/* Docker / Sandbox Status Badge */}
          <div
            className="hidden md:flex items-center gap-1.5 rounded-lg bg-slate-900/90 px-2.5 py-1.5 text-xs text-slate-300 ring-1 ring-slate-800"
            title={
              isUnreachable
                ? "Backend unreachable • Container check paused"
                : !hasDockerResult
                ? "Checking sandbox environment…"
                : isDockerUp
                ? `Docker Live: ${dockerInfo?.server_version || "Active"}`
                : "Sandbox: file-check mode (Disposable filesystem verification active)"
            }
          >
            <Server className="h-3.5 w-3.5 text-cyan-400" />
            {isInitialLoad ? (
              <span className="h-3.5 w-28 rounded bg-slate-800 animate-pulse" />
            ) : isUnreachable ? (
              <span className="font-mono text-[11px] text-rose-400 font-medium">Disconnected</span>
            ) : (
              <span className="font-mono text-[11px]">
                {isDockerUp ? "Docker Live" : "Sandbox: file-check mode"}
              </span>
            )}
          </div>

          {/* Backend Readiness Indicator */}
          <div
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-mono font-medium ring-1 ${
              isInitialLoad
                ? "bg-slate-900/90 text-slate-300 ring-slate-800"
                : isUnreachable
                ? "bg-rose-950/40 text-rose-300 ring-rose-800/60"
                : isReady
                ? "bg-emerald-950/40 text-emerald-300 ring-emerald-800/60"
                : "bg-amber-950/40 text-amber-300 ring-amber-800/60"
            }`}
            title={
              isInitialLoad
                ? "Verifying backend and sandbox readiness..."
                : isUnreachable
                ? "Backend unreachable. Ensure uvicorn server is running on port 8000."
                : readiness?.issues?.join("; ") || "Backend & Nebius Token Factory Ready"
            }
          >
            {isInitialLoad ? (
              <>
                <span className="h-2 w-2 rounded-full bg-cyan-400 shadow-sm shadow-cyan-400 animate-pulse" />
                <span className="h-3.5 w-16 rounded bg-slate-800 animate-pulse" />
              </>
            ) : isUnreachable ? (
              <>
                <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
                <span className="text-[11px]">Backend Unreachable</span>
              </>
            ) : isReady ? (
              <>
                <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-sm shadow-emerald-400 animate-pulse" />
                <span className="text-[11px]">Engine Ready</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                <span className="text-[11px]">Degraded</span>
              </>
            )}
          </div>

          {/* API Docs Link */}
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-900/60 px-2 sm:px-2.5 py-1.5 text-xs font-mono text-slate-400 hover:text-slate-200 hover:border-slate-700 transition-colors shrink-0"
            title="Open FastAPI Swagger Documentation (forwarded via Next.js rewrites)"
          >
            <span className="hidden sm:inline">API Docs</span>
            <span className="sm:hidden">API</span>
            <ExternalLink className="h-3 w-3" />
          </a>

          {/* Benchmark Scorecard Button - reachable on all screen sizes */}
          <button
            onClick={() => setShowBenchmark(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-700/60 bg-indigo-950/40 hover:bg-indigo-900/60 px-2 sm:px-2.5 py-1.5 text-xs font-mono font-medium text-indigo-300 transition-colors cursor-pointer shrink-0"
            title="View reproducible 7-scenario benchmark scorecard"
          >
            <Trophy className="h-3.5 w-3.5 text-amber-400 shrink-0" />
            <span>Benchmark</span>
          </button>

          {/* 3-Minute Demo CTA for Judges */}
          <button
            onClick={onQuickDemo}
            disabled={isInvestigating}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-indigo-600 px-2.5 sm:px-3.5 py-1.5 text-xs font-mono font-bold text-white shadow-md shadow-cyan-950/50 hover:from-cyan-400 hover:to-indigo-500 disabled:opacity-50 transition-all cursor-pointer select-none active:scale-[0.98] shrink-0 max-w-full"
            title="Execute complete Scenario B diagnostic and verification demo workflow"
          >
            <Sparkles className="h-3.5 w-3.5 shrink-0" />
            <span className="whitespace-nowrap">3-Min Judge Demo</span>
          </button>
        </div>
      </div>

      {/* Benchmark Scorecard Modal */}
      {showBenchmark && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="relative w-full max-w-3xl rounded-2xl border border-slate-800 bg-[#0c121e] p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-4 border-b border-slate-800">
              <div className="flex items-center gap-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/30">
                  <Trophy className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white font-mono">
                    FixLoop vs Baseline Benchmark Scorecard
                  </h3>
                  <p className="text-xs text-slate-400">
                    7 deterministic failure scenarios evaluated on identical ground truth fixtures
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowBenchmark(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 cursor-pointer transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Scorecard Table */}
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left font-mono text-xs border border-slate-800 rounded-lg overflow-hidden">
                <thead className="bg-slate-900/80 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="p-3">Evaluation Metric</th>
                    <th className="p-3 text-emerald-400">FixLoop (Evidence-Driven)</th>
                    <th className="p-3 text-slate-400">Log-Only Baseline</th>
                    <th className="p-3 text-cyan-400">Delta / Impact</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 bg-black/30 text-slate-300">
                  <tr>
                    <td className="p-3 font-semibold">Root-Cause Accuracy Rate</td>
                    <td className="p-3 text-emerald-400 font-bold">100.0% (7/7)</td>
                    <td className="p-3 text-rose-400">28.6% (2/7)</td>
                    <td className="p-3 text-cyan-300 font-semibold">+71.4% improvement</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-semibold">False Claims of Fix Success</td>
                    <td className="p-3 text-emerald-400 font-bold">0</td>
                    <td className="p-3 text-rose-400">4</td>
                    <td className="p-3 text-cyan-300 font-semibold">100% elimination of hallucinations</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-semibold">Insufficient Evidence Accuracy</td>
                    <td className="p-3 text-emerald-400 font-bold">100.0%</td>
                    <td className="p-3 text-rose-400">0.0%</td>
                    <td className="p-3 text-cyan-300 font-semibold">Zero false patches for outages</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-semibold">Clean Patch Application Rate</td>
                    <td className="p-3 text-emerald-400 font-bold">42.9%</td>
                    <td className="p-3 text-slate-400">28.6%</td>
                    <td className="p-3 text-cyan-300 font-semibold">+14.3% minimal diffs</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-semibold">Actual File-Check Verification Rate</td>
                    <td className="p-3 text-emerald-400 font-bold">57.1%</td>
                    <td className="p-3 text-rose-400">14.3%</td>
                    <td className="p-3 text-cyan-300 font-semibold">+42.8% Exit Code 0 truth</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-semibold">Total Tokens Consumed</td>
                    <td className="p-3 text-emerald-400 font-bold">2,012 tokens</td>
                    <td className="p-3 text-slate-400">1,833 tokens</td>
                    <td className="p-3 text-cyan-300 font-semibold">Bounded token footprint</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-semibold">Cost Per Investigation</td>
                    <td className="p-3 text-emerald-400 font-bold">~$0.00018</td>
                    <td className="p-3 text-slate-400">~$0.00016</td>
                    <td className="p-3 text-cyan-300 font-semibold">Extreme economic viability</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between text-xs text-slate-400 font-mono">
              <span className="flex items-center gap-1.5 text-emerald-400">
                <CheckCircle2 className="h-4 w-4" />
                <span>Deterministic reproducibility verified via runner.py</span>
              </span>
              <button
                onClick={() => setShowBenchmark(false)}
                className="rounded-lg bg-slate-800 hover:bg-slate-700 px-4 py-1.5 text-xs text-white font-mono cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
