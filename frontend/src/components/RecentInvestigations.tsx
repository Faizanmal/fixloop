"use client";

import React, { useState } from "react";
import {
  getStatusColor,
  formatDuration,
  formatScenarioTargetName,
  formatRecordedTimestamp,
} from "@/lib/utils";
import { History, ArrowUpRight, ArrowUpDown, Eye, Trash2 } from "lucide-react";
import { InvestigationHistoryItem } from "@/lib/api";

interface RecentInvestigationsProps {
  history: InvestigationHistoryItem[];
  onSelectHistoryItem: (item: InvestigationHistoryItem) => void;
  activeInspectId?: string | null;
  isLoadingInspect?: boolean;
  onClearHistory?: () => void;
}

function parseSafeEpoch(isoOrTimeString?: string | null): number {
  if (!isoOrTimeString) return 0;
  const t = new Date(isoOrTimeString).getTime();
  return isNaN(t) ? 0 : t;
}

export const RecentInvestigations = React.memo(function RecentInvestigations({
  history,
  onSelectHistoryItem,
  activeInspectId,
  isLoadingInspect,
  onClearHistory,
}: RecentInvestigationsProps) {
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  if (history.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-center mb-8">
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

  // Sort history: "desc" puts newer runs first (N→1), "asc" puts older runs first (1→N)
  const sortedHistory = [...history].sort((a, b) => {
    // Primary: sort by startedAtIso epoch timestamp
    const timeA = parseSafeEpoch(a.startedAtIso);
    const timeB = parseSafeEpoch(b.startedAtIso);
    if (timeA > 0 && timeB > 0 && timeA !== timeB) {
      return sortOrder === "desc" ? timeB - timeA : timeA - timeB;
    }

    // Secondary: parse numeric part of id (e.g. inv-0008 -> 8, RUN-1234 -> 1234)
    const numA = parseInt(a.id.replace(/\D/g, ""), 10) || 0;
    const numB = parseInt(b.id.replace(/\D/g, ""), 10) || 0;
    if (numA !== numB) {
      return sortOrder === "desc" ? numB - numA : numA - numB;
    }

    // Fallback: natural locale string compare
    return sortOrder === "desc"
      ? b.id.localeCompare(a.id, undefined, { numeric: true })
      : a.id.localeCompare(b.id, undefined, { numeric: true });
  });

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-5 shadow-sm mb-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
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
        <div className="flex items-center gap-3">
          <button
            onClick={() => setSortOrder(prev => (prev === "desc" ? "asc" : "desc"))}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-2.5 py-1 text-[11px] font-mono text-slate-300 hover:text-white hover:border-slate-600 transition-colors cursor-pointer"
            title="Toggle chronological vs reverse ordering"
          >
            <ArrowUpDown className="h-3 w-3 text-cyan-400" />
            <span>Order: {sortOrder === "desc" ? "Newest First (N→1)" : "Oldest First (1→N)"}</span>
          </button>
          {onClearHistory && (
            <button
              onClick={onClearHistory}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-2 py-1 text-[11px] font-mono text-slate-400 hover:text-rose-300 hover:border-rose-800/80 transition-colors cursor-pointer"
              title="Clear local audit history"
            >
              <Trash2 className="h-3 w-3" />
              <span>Clear History</span>
            </button>
          )}
          <span className="text-xs text-slate-400 font-mono">
            {sortedHistory.length} logged run(s)
          </span>
        </div>
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
            {sortedHistory.map((item) => {
              const statusStyles = getStatusColor(item.status);
              const isInspecting = item.id.toLowerCase() === activeInspectId?.toLowerCase();
              return (
                <tr
                  key={item.id}
                  className={`hover:bg-slate-800/30 transition-colors group cursor-pointer ${
                    isInspecting ? "bg-cyan-950/30 border-l-2 border-l-cyan-400" : ""
                  }`}
                  onClick={() => onSelectHistoryItem(item)}
                >
                  <td className="py-3 text-cyan-300 font-bold">
                    <div className="flex items-center gap-1.5">
                      <span>{item.id}</span>
                      {isInspecting && (
                        <span className="rounded bg-cyan-500/20 border border-cyan-500/40 px-1.5 py-0.5 text-[9px] font-mono text-cyan-300 font-semibold flex items-center gap-1">
                          {isLoadingInspect ? (
                            <>
                              <div className="h-2 w-2 animate-spin rounded-full border border-cyan-300 border-t-transparent" />
                              Loading run…
                            </>
                          ) : (
                            <>
                              <Eye className="h-2.5 w-2.5" />
                              Viewing
                            </>
                          )}
                        </span>
                      )}
                      {item.isSample && (
                        <span className="rounded bg-slate-800 border border-slate-700 px-1.5 py-0.5 text-[9px] font-mono text-slate-400 font-normal">
                          Sample
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 text-slate-200">
                    <span className="font-medium text-cyan-200/90 font-mono">
                      {formatScenarioTargetName(item.scenarioName)}
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
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1.5">
                        <span>{formatDuration(item.durationMs)}</span>
                        {item.isCached && (
                          <span className="rounded bg-indigo-500/20 border border-indigo-500/40 px-1.5 py-0.2 text-[9px] font-mono text-indigo-300 font-semibold">
                            Cached
                          </span>
                        )}
                      </div>
                      {item.isCached && (
                        <span className="text-[10px] text-slate-500 font-mono">
                          Compute: {formatDuration(item.originalDurationMs || item.diagnosisDurationMs || item.durationMs)}
                          {typeof item.lookupDurationMs === "number" && ` · Lookup: ${formatDuration(item.lookupDurationMs)}`}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 text-slate-400 text-[11px] whitespace-nowrap" title={item.startedAtIso || item.timestamp}>
                    {formatRecordedTimestamp(item.startedAtIso || item.timestamp)}
                  </td>
                  <td className="py-3 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectHistoryItem(item);
                      }}
                      className={`inline-flex items-center gap-1 font-medium cursor-pointer group-hover:underline ${
                        isInspecting
                          ? "text-cyan-300 font-bold"
                          : "text-cyan-400 hover:text-cyan-300"
                      }`}
                    >
                      <span>{isInspecting ? (isLoadingInspect ? "Loading…" : "Inspecting") : "Inspect"}</span>
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
});
