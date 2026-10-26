"use client";

import React from "react";
import { SystemReadiness } from "@/lib/api";
import {
  ShieldAlert,
  Cpu,
  AlertTriangle,
  Sparkles,
} from "lucide-react";

interface NavbarProps {
  readiness: SystemReadiness | null;
  onQuickDemo: () => void;
  isInvestigating: boolean;
}

export function Navbar({
  readiness,
  onQuickDemo,
  isInvestigating,
}: NavbarProps) {
  const isReady = readiness?.ready ?? false;
  const modelName = readiness?.model_name || "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B";

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800 bg-[#090d16]/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-600 to-indigo-600 shadow-lg shadow-cyan-950/50 ring-1 ring-cyan-400/30">
            <ShieldAlert className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold tracking-tight text-white font-mono">
                FixLoop
              </span>
              <span className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-[10px] font-semibold text-cyan-400 ring-1 ring-cyan-500/30">
                v0.1 MVP
              </span>
              <span className="hidden sm:inline-flex rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium text-indigo-400 ring-1 ring-indigo-500/30">
                Nebius x NVIDIA Hackathon
              </span>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">
              Evidence-Driven Autonomous Debugging Agent
            </p>
          </div>
        </div>

        {/* Model & Backend Health Status */}
        <div className="flex items-center gap-2 sm:gap-4">
          {/* Target Model Badge */}
          <div className="hidden md:flex items-center gap-2 rounded-lg bg-slate-900/80 px-2.5 py-1.5 text-xs text-slate-300 ring-1 ring-slate-800">
            <Cpu className="h-3.5 w-3.5 text-cyan-400" />
            <span className="font-mono text-[11px] text-slate-400">Model:</span>
            <span className="font-mono text-[11px] text-cyan-300 max-w-[180px] truncate" title={modelName}>
              {modelName.split("/").pop()}
            </span>
          </div>

          {/* Backend Readiness Indicator */}
          <div
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1 ${
              isReady
                ? "bg-emerald-950/40 text-emerald-300 ring-emerald-800/60"
                : readiness === null
                ? "bg-slate-900 text-slate-400 ring-slate-800"
                : "bg-amber-950/40 text-amber-300 ring-amber-800/60"
            }`}
            title={
              readiness?.issues?.join("; ") ||
              (isReady ? "Backend and Nebius LLM ready" : "Connecting to backend...")
            }
          >
            {isReady ? (
              <>
                <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-sm shadow-emerald-400" />
                <span className="text-[11px]">Engine Ready</span>
              </>
            ) : readiness === null ? (
              <>
                <span className="h-2 w-2 rounded-full bg-slate-400 animate-pulse" />
                <span className="text-[11px]">Connecting...</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                <span className="text-[11px]">Degraded / Offline</span>
              </>
            )}
          </div>

          {/* Demo 1-Click Trigger */}
          <button
            onClick={onQuickDemo}
            disabled={isInvestigating}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-indigo-600 px-3 py-1.5 text-xs font-semibold text-white shadow-md shadow-cyan-950/40 hover:from-cyan-400 hover:to-indigo-500 disabled:opacity-50 transition-all cursor-pointer"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">3-Min Judge Demo</span>
            <span className="sm:hidden">Demo</span>
          </button>
        </div>
      </div>
    </header>
  );
}
