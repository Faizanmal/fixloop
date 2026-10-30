"use client";

import React from "react";
import { SystemReadiness, ScenarioInfo } from "@/lib/api";
import { formatModelName } from "@/lib/utils";
import {
  Server,
  ShieldCheck,
  Layers,
  Cpu,
  CheckCircle2,
} from "lucide-react";

interface ProjectHealthSummaryProps {
  readiness: SystemReadiness | null;
  activeScenario: ScenarioInfo | null;
  currentTargetName?: string;
  totalDiagnosesCount: number;
}

export function ProjectHealthSummary({
  readiness,
  activeScenario,
  currentTargetName,
  totalDiagnosesCount,
}: ProjectHealthSummaryProps) {
  const isInitialLoad = readiness === null;
  const dockerInfo = readiness?.docker;
  const hasDockerResult = dockerInfo !== undefined && dockerInfo !== null;
  const isDockerUp = dockerInfo?.available === true;

  const nebiusInfo = readiness?.nebius;
  const hasNebiusResult = nebiusInfo !== undefined && nebiusInfo !== null;
  const isNebiusConfigured = nebiusInfo?.api_key_configured ?? false;
  const isMockMode = nebiusInfo?.mock_mode ?? false;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      {/* 1. Docker Runtime & Sandbox Isolation */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Runtime Isolation
          </span>
          <Server className="h-4 w-4 text-cyan-400" />
        </div>
        {!hasDockerResult ? (
          <>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-white font-mono">
                Checking sandbox…
              </span>
              <span
                className="h-2 w-2 rounded-full bg-cyan-400 animate-pulse"
                title="Checking sandbox environment..."
              />
            </div>
            <p className="mt-1 text-xs text-slate-400 leading-relaxed">
              Detecting container runtime / isolation mode…
            </p>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-white font-mono">
                {isDockerUp ? "Docker Daemon" : "Sandbox: file-check"}
              </span>
              <span
                className="h-2 w-2 rounded-full bg-emerald-400"
                title={isDockerUp ? "Docker daemon active" : "Sandbox file-check mode active"}
              />
            </div>
            <p className="mt-1 text-xs text-slate-400 leading-relaxed">
              {isDockerUp
                ? `Docker Engine ${dockerInfo?.server_version || "Active"}`
                : "Sandbox: file-check mode (Zero socket exposure)"}
            </p>
          </>
        )}
      </div>

      {/* 2. Nebius Token Factory & NVIDIA Model */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Nebius Token Factory
          </span>
          <Cpu className="h-4 w-4 text-indigo-400" />
        </div>
        {!hasNebiusResult ? (
          <>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-white font-mono truncate">
                Checking engine…
              </span>
              <span
                className="h-2 w-2 rounded-full bg-indigo-400 animate-pulse"
                title="Connecting to Nebius Token Factory..."
              />
            </div>
            <p className="mt-1 text-xs text-slate-400 leading-relaxed truncate">
              Connecting to Nebius Token Factory…
            </p>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-white font-mono truncate">
                {isMockMode
                  ? "Mock Engine"
                  : isNebiusConfigured
                  ? "Nemotron Live"
                  : "Unconfigured"}
              </span>
              {isMockMode ? (
                <span className="rounded bg-indigo-950 px-1.5 py-0.5 text-[9px] font-mono text-indigo-300 border border-indigo-800">
                  Deterministic
                </span>
              ) : isNebiusConfigured ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
              ) : (
                <span className="rounded bg-amber-950 px-1.5 py-0.5 text-[9px] font-mono text-amber-300 border border-amber-800">
                  Offline
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-slate-400 leading-relaxed truncate" title={formatModelName(nebiusInfo?.model)}>
              {formatModelName(nebiusInfo?.model)}
            </p>
          </>
        )}
      </div>

      {/* 3. Security Boundaries & Guardrails */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Security Invariants
          </span>
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold text-emerald-400 font-mono">
            Zero Shell Exec
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-400 leading-relaxed">
          Path traversal blocked • Strict probe allowlist • Zero token leaks
        </p>
      </div>

      {/* 4. Target & Diagnostic Budget */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm backdrop-blur">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Target & Budget
          </span>
          <Layers className="h-4 w-4 text-amber-400" />
        </div>
        <div className="flex items-baseline gap-2 truncate">
          <span
            className="text-lg font-bold text-amber-300 font-mono truncate"
            title={activeScenario ? activeScenario.name : (currentTargetName || "Custom Target")}
          >
            {activeScenario
              ? activeScenario.name.split(":")[0]
              : currentTargetName
              ? `Custom: ${currentTargetName}`
              : "Custom Log Target"}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-400 leading-relaxed truncate">
          {activeScenario
            ? `Difficulty: ${activeScenario.difficulty} • ${totalDiagnosesCount} run(s) logged`
            : `Custom Input Target • ${totalDiagnosesCount} run(s) logged`}
        </p>
      </div>
    </div>
  );
}
