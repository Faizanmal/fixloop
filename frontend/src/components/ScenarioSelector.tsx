"use client";

import React, { useState, useEffect, useRef } from "react";
import { ScenarioInfo } from "@/lib/api";
import {
  FileWarning,
  HeartCrack,
  Network,
  HelpCircle,
  Play,
  Layers,
  ArrowRight,
  UploadCloud,
  Sparkles,
  Loader2,
  AlertTriangle,
  RotateCcw,
} from "lucide-react";

interface ScenarioSelectorProps {
  scenarios: ScenarioInfo[];
  selectedScenario: string;
  onSelectScenario: (id: string) => void;
  onStartInvestigation: () => void;
  onCustomDiagnose?: (serviceName: string, logs: string) => void;
  onCancelInvestigation?: () => void;
  isInvestigating: boolean;
}

interface ActiveDiagnosticProgressProps {
  onCancel?: () => void;
  onRetry?: () => void;
}

function ActiveDiagnosticProgress({ onCancel, onRetry }: ActiveDiagnosticProgressProps) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const timer = setInterval(() => {
      setSeconds(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-cyan-500/30 bg-cyan-950/20 p-4 font-mono text-xs">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent will-change-transform transform-gpu" />
            <span>Diagnosing with Nebius ({seconds}s)...</span>
          </div>
          <span className="text-slate-400 text-[11px] font-mono">
            Elapsed: {seconds}s
          </span>
        </div>
        <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
          <div
            className="bg-gradient-to-r from-cyan-500 to-indigo-500 h-1.5 rounded-full transition-all duration-500"
            style={{
              width: `${Math.min(95, Math.max(10, seconds * 2.5))}%`,
            }}
          />
        </div>
        <p className="text-[11px] text-slate-400 mt-2">
          Deep LLM inference via Nebius typically takes 5–8s for container trace analysis (cached runs &lt;10ms). Engine will automatically timeout if VM does not respond within 90s.
        </p>
      </div>

      {seconds >= 90 && (
        <div className="rounded-lg border border-amber-500/50 bg-amber-950/60 p-4 text-xs font-mono text-amber-200 animate-in fade-in">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="font-bold text-amber-300">
                This is taking longer than expected ({seconds}s)
              </div>
              <p className="text-[11px] text-slate-300 mt-1 leading-relaxed">
                Nebius Token Factory inference or VM response took longer than 90 seconds. You can click Retry to cancel and re-submit a fresh request.
              </p>
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={onRetry}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-amber-600 bg-amber-900/80 px-3 py-1.5 text-xs font-mono font-medium text-amber-100 hover:bg-amber-800 transition-colors cursor-pointer"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  <span>Retry</span>
                </button>
                <button
                  type="button"
                  onClick={onCancel}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-xs font-mono text-slate-300 hover:text-white transition-colors cursor-pointer"
                >
                  <span>Cancel</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export const ScenarioSelector = React.memo(function ScenarioSelector({
  scenarios,
  selectedScenario,
  onSelectScenario,
  onStartInvestigation,
  onCustomDiagnose,
  onCancelInvestigation,
  isInvestigating,
}: ScenarioSelectorProps) {
  const [activeTab, setActiveTab] = useState<"scenarios" | "custom">("scenarios");
  const [customServiceName, setCustomServiceName] = useState<string>("auth-service");
  const [customLogs, setCustomLogs] = useState<string>("");
  const isSubmittingRef = useRef<boolean>(false);

  useEffect(() => {
    if (!isInvestigating) {
      isSubmittingRef.current = false;
    }
  }, [isInvestigating]);

  const getScenarioIcon = (id: string) => {
    if (id.includes("scenario_a")) return FileWarning;
    if (id.includes("scenario_b")) return HeartCrack;
    if (id.includes("scenario_c")) return Network;
    return HelpCircle;
  };

  const getDifficultyBadge = (difficulty: string) => {
    switch (difficulty) {
      case "Easy":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
      case "Medium":
        return "bg-amber-500/10 text-amber-400 border-amber-500/30";
      case "Hard":
        return "bg-purple-500/10 text-purple-400 border-purple-500/30";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  const handleCustomSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customLogs.trim() || isInvestigating || isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    onCustomDiagnose?.(customServiceName, customLogs);
    setTimeout(() => {
      isSubmittingRef.current = false;
    }, 1000);
  };

  return (
    <div className="mb-8">
      {/* Top Header and Tab Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2.5 py-0.5 text-xs font-mono font-bold text-cyan-400">
              TARGET PROJECT SELECTION
            </span>
            <span className="hidden sm:inline-flex items-center gap-1 text-[11px] font-mono text-slate-400">
              <Sparkles className="h-3 w-3 text-cyan-400" />
              Pre-configured scenarios ready for 3-min judge reproduction
            </span>
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Layers className="h-5 w-5 text-cyan-400" />
            Project & Failure Scenario Workspace
          </h2>
        </div>

        {/* Action Button & Tabs */}
        <div className="flex items-center gap-3">
          <div className="inline-flex rounded-lg bg-black/40 p-1 border border-slate-800 text-xs font-mono">
            <button
              onClick={() => {
                setActiveTab("scenarios");
                const isPreset = scenarios.some((s) => s.id === selectedScenario);
                if (!isPreset && scenarios.length > 0) {
                  onSelectScenario(scenarios[0].id);
                }
              }}
              className={`px-3 py-1.5 rounded-md transition-all cursor-pointer ${
                activeTab === "scenarios"
                  ? "bg-slate-800 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Preset Benchmarks ({scenarios.length})
            </button>
            <button
              onClick={() => setActiveTab("custom")}
              className={`px-3 py-1.5 rounded-md transition-all cursor-pointer ${
                activeTab === "custom"
                  ? "bg-slate-800 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Upload Custom Logs
            </button>
          </div>

          {activeTab === "scenarios" && (
            <button
              onClick={() => {
                const isPreset = scenarios.some((s) => s.id === selectedScenario);
                if (!isPreset && scenarios.length > 0) {
                  onSelectScenario(scenarios[0].id);
                }
                onStartInvestigation();
              }}
              disabled={isInvestigating || (!selectedScenario && scenarios.length === 0)}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-indigo-600 px-5 py-2 text-xs font-semibold text-white shadow-lg shadow-cyan-950/50 hover:from-cyan-400 hover:to-indigo-500 disabled:opacity-50 transition-all cursor-pointer font-mono select-none"
            >
              {isInvestigating ? (
                <>
                  <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  <span>Investigating...</span>
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5 fill-white" />
                  <span>Start Investigation</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Preset Scenarios Grid */}
      {activeTab === "scenarios" ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {scenarios.map((sc) => {
              const isSelected = selectedScenario === sc.id;
              const IconComponent = getScenarioIcon(sc.id);

              return (
                <div
                  key={sc.id}
                  onClick={() => onSelectScenario(sc.id)}
                  className={`relative flex flex-col justify-between rounded-xl border p-4 cursor-pointer transition-colors duration-150 select-none ${
                    isSelected
                      ? "border-cyan-500 bg-cyan-950/25 ring-1 ring-cyan-500/50 shadow-md shadow-cyan-950/40"
                      : "border-slate-800 bg-slate-900/50 hover:border-slate-700 hover:bg-slate-900/80"
                  }`}
                >
                  <div>
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <div
                        className={`flex h-9 w-9 items-center justify-center rounded-lg ring-1 ${
                          isSelected
                            ? "bg-cyan-500/20 text-cyan-300 ring-cyan-500/40"
                            : "bg-slate-800 text-slate-400 ring-slate-700"
                        }`}
                      >
                        <IconComponent className="h-5 w-5" />
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-mono font-semibold ${getDifficultyBadge(
                            sc.difficulty
                          )}`}
                        >
                          {sc.difficulty}
                        </span>
                        {sc.requires_probe && (
                          <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-1.5 py-0.2 text-[9px] font-mono text-cyan-400 font-medium">
                            Active Probe
                          </span>
                        )}
                      </div>
                    </div>

                    <h3
                      className={`text-sm font-semibold mb-1 leading-snug ${
                        isSelected ? "text-cyan-200" : "text-slate-200"
                      }`}
                    >
                      {sc.name.split(":")[0]}
                    </h3>
                    <p className="text-xs text-slate-400 leading-relaxed mb-4 line-clamp-3">
                      {sc.description}
                    </p>
                  </div>

                  <div className="flex items-center justify-between pt-2.5 border-t border-slate-800/80 text-[11px] font-mono">
                    <span className="text-slate-500">
                      {sc.id.replace("scenario_", "SC-")}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 font-semibold ${
                        isSelected ? "text-cyan-400" : "text-slate-400"
                      }`}
                    >
                      {isSelected ? "Active Target" : "Select Target"}
                      <ArrowRight className="h-3 w-3" />
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          {isInvestigating && (
            <ActiveDiagnosticProgress
              onCancel={() => onCancelInvestigation?.()}
              onRetry={() => {
                onCancelInvestigation?.();
                setTimeout(() => {
                  onStartInvestigation();
                }, 150);
              }}
            />
          )}
        </div>
      ) : (
        /* Custom Logs Ingestion Form */
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm">
          <form onSubmit={handleCustomSubmit} className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-4">
              <div className="flex-1">
                <label className="block text-xs font-mono text-slate-300 mb-1">
                  Service / Container Identifier
                </label>
                <input
                  type="text"
                  value={customServiceName}
                  onChange={(e) => setCustomServiceName(e.target.value)}
                  placeholder="e.g. payment-service"
                  className="w-full rounded-lg border border-slate-800 bg-black/40 px-3 py-2 text-xs font-mono text-slate-200 placeholder-slate-600 focus:border-cyan-500 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1">
                Container Console Logs / Traceback
              </label>
              <textarea
                value={customLogs}
                onChange={(e) => setCustomLogs(e.target.value)}
                placeholder="Paste container crash logs, Python traceback, or Docker exit messages here..."
                rows={5}
                className="w-full rounded-lg border border-slate-800 bg-black/40 p-3 text-xs font-mono text-slate-200 placeholder-slate-600 focus:border-cyan-500 focus:outline-none"
              />
            </div>

            {isInvestigating && (
              <ActiveDiagnosticProgress
                onCancel={() => onCancelInvestigation?.()}
                onRetry={() => {
                  onCancelInvestigation?.();
                  setTimeout(() => {
                    onCustomDiagnose?.(customServiceName, customLogs);
                  }, 150);
                }}
              />
            )}

            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2">
              <span className="text-xs font-mono text-slate-400">
                Secrets, API keys, and authorization headers are automatically masked by the ingestion engine.
              </span>
              <button
                type="submit"
                disabled={isInvestigating || !customLogs.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-indigo-600 px-5 py-2 text-xs font-semibold text-white shadow-md shadow-cyan-950/40 hover:from-cyan-400 hover:to-indigo-500 disabled:opacity-50 transition-all cursor-pointer font-mono"
              >
                {isInvestigating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin text-cyan-200 will-change-transform transform-gpu" />
                    <span>Diagnosing with Nebius...</span>
                  </>
                ) : (
                  <>
                    <UploadCloud className="h-4 w-4" />
                    <span>Diagnose Uploaded Logs</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
});
