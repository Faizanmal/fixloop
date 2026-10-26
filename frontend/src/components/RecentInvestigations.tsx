"use client";

import React from "react";
import { getStatusColor, formatDuration } from "@/lib/utils";
import { History, ArrowUpRight } from "lucide-react";

export interface InvestigationHistoryItem {
  id: string;
  scenarioName: string;
  status: string;
  confidence: number;
  durationMs: number;
  timestamp: string;
}

interface RecentInvestigationsProps {
  history: InvestigationHistoryItem[];
  onSelectHistoryItem: (item: InvestigationHistoryItem) => void;
}

export function RecentInvestigations({
  history,
  onSelectHistoryItem,
}: RecentInvestigationsProps) {
  if (history.length === 0) {
    return null;
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm backdrop-blur mb-8">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-bold text-white flex items-center gap-2">
          <History className="h-4 w-4 text-cyan-400" />
          Recent Diagnostic Investigations
        </h3>
        <span className="text-xs text-slate-400 font-mono">
          {history.length} auditable runs
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-[11px] font-mono text-slate-400 uppercase">
              <th className="pb-2.5 font-medium">Run ID</th>
              <th className="pb-2.5 font-medium">Scenario / Target</th>
              <th className="pb-2.5 font-medium">Outcome Status</th>
              <th className="pb-2.5 font-medium">Confidence</th>
              <th className="pb-2.5 font-medium">Duration</th>
              <th className="pb-2.5 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {history.map((item) => {
              const statusStyles = getStatusColor(item.status);
              return (
                <tr key={item.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="py-2.5 text-slate-400 font-bold">{item.id}</td>
                  <td className="py-2.5 text-slate-200">
                    {item.scenarioName.replace("scenario_", "").replace(/_/g, " ")}
                  </td>
                  <td className="py-2.5">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${statusStyles.badge}`}
                    >
                      {item.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="py-2.5 text-slate-300">
                    {(item.confidence * 100).toFixed(0)}%
                  </td>
                  <td className="py-2.5 text-slate-400">
                    {formatDuration(item.durationMs)}
                  </td>
                  <td className="py-2.5 text-right">
                    <button
                      onClick={() => onSelectHistoryItem(item)}
                      className="inline-flex items-center gap-1 text-cyan-400 hover:text-cyan-300 font-medium cursor-pointer"
                    >
                      <span>Inspect</span>
                      <ArrowUpRight className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
