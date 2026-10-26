"use client";

import React from "react";
import { ScenarioInfo } from "@/lib/api";
import {
  FileWarning,
  HeartCrack,
  Network,
  HelpCircle,
  Play,
  Layers,
  ArrowRight,
} from "lucide-react";

interface ScenarioSelectorProps {
  scenarios: ScenarioInfo[];
  selectedScenario: string;
  onSelectScenario: (id: string) => void;
  onStartInvestigation: () => void;
  isInvestigating: boolean;
}

export function ScenarioSelector({
  scenarios,
  selectedScenario,
  onSelectScenario,
  onStartInvestigation,
  isInvestigating,
}: ScenarioSelectorProps) {
  const getScenarioIcon = (id: string) => {
    if (id.includes("scenario_a")) return FileWarning;
    if (id.includes("scenario_b")) return HeartCrack;
    if (id.includes("scenario_c")) return Network;
    return HelpCircle;
  };

  const getDifficultyBadge = (difficulty: string) => {
    switch (difficulty) {
      case "Easy":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "Medium":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      case "Hard":
        return "bg-purple-500/10 text-purple-400 border-purple-500/20";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  return (
    <div className="mb-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Layers className="h-5 w-5 text-cyan-400" />
            Reproducible Failure Scenarios
          </h2>
          <p className="text-sm text-slate-400">
            Select a benchmark scenario to investigate with FixLoop&apos;s evidence-driven engine.
          </p>
        </div>

        {/* Start Investigation Button */}
        <button
          onClick={onStartInvestigation}
          disabled={isInvestigating || !selectedScenario}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-950/50 hover:from-cyan-400 hover:to-indigo-500 disabled:opacity-50 transition-all cursor-pointer font-mono"
        >
          {isInvestigating ? (
            <>
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              <span>Investigating Evidence...</span>
            </>
          ) : (
            <>
              <Play className="h-4 w-4 fill-white" />
              <span>Start Investigation</span>
            </>
          )}
        </button>
      </div>

      {/* Grid of Scenarios */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {scenarios.map((sc) => {
          const isSelected = selectedScenario === sc.id;
          const IconComponent = getScenarioIcon(sc.id);

          return (
            <div
              key={sc.id}
              onClick={() => onSelectScenario(sc.id)}
              className={`relative flex flex-col justify-between rounded-xl border p-4 cursor-pointer transition-all duration-200 ${
                isSelected
                  ? "border-cyan-500 bg-cyan-950/20 ring-1 ring-cyan-500/50 shadow-md shadow-cyan-950/40"
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
                      className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${getDifficultyBadge(
                        sc.difficulty
                      )}`}
                    >
                      {sc.difficulty}
                    </span>
                    {sc.requires_probe && (
                      <span className="rounded-full bg-cyan-500/10 border border-cyan-500/20 px-1.5 py-0.2 text-[9px] font-medium text-cyan-400">
                        Active Probe
                      </span>
                    )}
                  </div>
                </div>

                <h3
                  className={`text-sm font-semibold mb-1 line-clamp-1 ${
                    isSelected ? "text-cyan-200" : "text-slate-200"
                  }`}
                  title={sc.name}
                >
                  {sc.name.split(":")[0]}
                </h3>
                <p className="text-xs text-slate-400 line-clamp-3 leading-relaxed mb-4">
                  {sc.description}
                </p>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-slate-800/80 text-[11px]">
                <span className="font-mono text-slate-500">
                  {sc.id.replace("scenario_", "SC-")}
                </span>
                <span
                  className={`inline-flex items-center gap-1 font-medium ${
                    isSelected ? "text-cyan-400" : "text-slate-400"
                  }`}
                >
                  {isSelected ? "Selected" : "Select"}
                  <ArrowRight className="h-3 w-3" />
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
