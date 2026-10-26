"use client";

import React from "react";
import { SystemReadiness, ScenarioInfo } from "@/lib/api";
import {
  Server,
  ShieldCheck,
  Layers,
  Clock,
} from "lucide-react";

interface ProjectHealthSummaryProps {
  readiness: SystemReadiness | null;
  activeScenario: ScenarioInfo | null;
  totalDiagnosesCount: number;
}

export function ProjectHealthSummary({
  readiness,
  activeScenario,
  totalDiagnosesCount,
}: ProjectHealthSummaryProps) {
  const dockerInfo = readiness?.docker_daemon;
  const isDockerUp = dockerInfo?.available ?? false;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      {/* 1. Docker & Runtime Environment */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Runtime Sandbox
          </span>
          <Server className="h-4 w-4 text-cyan-400" />
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-xl font-bold text-white font-mono">
            {isDockerUp ? "Docker Daemon" : "Disposable TempDir"}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          {isDockerUp
            ? `Docker Engine ${dockerInfo?.server_version || "Active"}`
            : "Filesystem & route isolation (Zero socket leak)"}
        </p>
      </div>

      {/* 2. Security Boundaries & Masking */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Security Boundaries
          </span>
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-xl font-bold text-emerald-400 font-mono">
            Enforced
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Path traversal blocked • Zero secret disclosure in logs
        </p>
      </div>

      {/* 3. Diagnostic Limits & Budget */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Diagnostic Budget
          </span>
          <Clock className="h-4 w-4 text-indigo-400" />
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-xl font-bold text-indigo-300 font-mono">
            5 Steps / 5.0s
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Strict iteration limit • {totalDiagnosesCount} investigations run
        </p>
      </div>

      {/* 4. Active Target Scenario */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Target Service
          </span>
          <Layers className="h-4 w-4 text-amber-400" />
        </div>
        <div className="flex items-baseline gap-2 truncate">
          <span className="text-lg font-bold text-amber-300 font-mono truncate" title={activeScenario?.name}>
            {activeScenario ? activeScenario.name.split(":")[0] : "None Selected"}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          {activeScenario ? `Difficulty: ${activeScenario.difficulty}` : "Select a scenario below"}
        </p>
      </div>
    </div>
  );
}
