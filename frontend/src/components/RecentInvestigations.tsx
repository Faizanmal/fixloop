"use client";

import React from "react";
import { getStatusColor, formatDuration } from "@/lib/utils";
import { History, ArrowUpRight } from "lucide-react";
import { InvestigationHistoryItem } from "@/lib/api";

interface RecentInvestigationsProps {
  history: InvestigationHistoryItem[];
  onSelectHistoryItem: (item: InvestigationHistoryItem) => void;
}

export function RecentInvestigations({
  history,
  onSelectHistoryItem,
}: RecentInvestigationsProps) {
  if (history.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 text-center backdrop-blur mb-8">
        <History className="h-6 w-6 text-slate-500 mx-auto mb-2" />
        <h4 className="text-sm font-semibold text-slate-300 font-mono">
          No Investigations Recorded Yet
        </h4>
        <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
          Select a scenario above and click &quot;Start Investigation&quot; or &quot;3-Min Judge Demo&quot; to begin an evidence-driven diagnostic cycle.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm backdrop-blur mb-8">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2 py-0.5 text-[10px] font-mono font-bold text-cyan-400">
              AUDIT TRAIL
            </span>
          </div>
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <History className="h-4 w-4 text-cyan-400" />
            Recent Diagnostic Investigations & Verification Runs
          </h3>
        </div>
        <span className="text-xs text-slate-400 font-mono">
          {history.length} logged run(s)
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-[11px] font-mono text-slate-400 uppercase tracking-wider">
              <th className="pb-3 font-medium">Run ID</th>
              <th className="pb-3 font-medium">Scenario / Target</th>
              <th className="pb-3 font-medium">Diagnostic Outcome</th>
              <th className="pb-3 font-medium">Calibrated Confidence</th>
              <th className="pb-3 font-medium">Duration</th>
              <th className="pb-3 font-medium">Recorded At</th>
              <th className="pb-3 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {history.map((item) => {
              const statusStyles = getStatusColor(item.status);
              return (
                <tr
                  key={item.id}
                  className="hover:bg-slate-800/30 transition-colors group cursor-pointer"
                  onClick={() => onSelectHistoryItem(item)}
                >
                  <td className="py-3 text-cyan-300 font-bold">
                    <div className="flex items-center gap-1.5">
                      <span>{item.id}</span>
                      {item.isSample && (
                        <span className="rounded bg-slate-800 border border-slate-700 px-1.5 py-0.5 text-[9px] font-mono text-slate-400 font-normal">
                          Sample
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 text-slate-200">
                    <span className="font-medium">
                      {item.scenarioName.replace("scenario_", "").replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="py-3">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase ${statusStyles.badge}`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${statusStyles.dot}`} />
                      {item.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className="py-3 text-slate-300 font-bold">
                    {(item.confidence * 100).toFixed(0)}%
                  </td>
                  <td className="py-3 text-slate-400">
                    {formatDuration(item.durationMs)}
                  </td>
                  <td className="py-3 text-slate-500 text-[11px]">
                    {item.timestamp}
                  </td>
                  <td className="py-3 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectHistoryItem(item);
                      }}
                      className="inline-flex items-center gap-1 text-cyan-400 hover:text-cyan-300 font-medium cursor-pointer group-hover:underline"
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
