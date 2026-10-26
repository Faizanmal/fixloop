"use client";

import React, { useState } from "react";
import { EvidenceRecord } from "@/lib/api";
import {
  FileText,
  Search,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

interface EvidenceViewerProps {
  evidence: EvidenceRecord[];
}

export function EvidenceViewer({ evidence }: EvidenceViewerProps) {
  const [filterType, setFilterType] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  const types = ["ALL", ...Array.from(new Set(evidence.map((e) => e.type)))];

  const filtered = evidence.filter((item) => {
    const matchesFilter = filterType === "ALL" || item.type === filterType;
    const matchesSearch =
      searchQuery === "" ||
      item.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.source.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const getTypeBadge = (type: string) => {
    switch (type.toUpperCase()) {
      case "LOG_EXTRACT":
        return "bg-cyan-500/10 text-cyan-400 border-cyan-500/30";
      case "CONTAINER_STATE":
        return "bg-amber-500/10 text-amber-400 border-amber-500/30";
      case "CONFIG_AUDIT":
        return "bg-indigo-500/10 text-indigo-400 border-indigo-500/30";
      case "DIAGNOSTIC_PROBE":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm backdrop-blur">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <FileText className="h-4 w-4 text-cyan-400" />
            Collected Empirical Evidence
          </h3>
          <p className="text-xs text-slate-400">
            Raw observations collected directly from container state, logs, and diagnostic checks.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5">
          {types.map((t) => (
            <button
              key={t}
              onClick={() => setFilterType(t)}
              className={`rounded-lg px-2.5 py-1 text-[11px] font-mono font-medium transition-all cursor-pointer ${
                filterType === t
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                  : "bg-slate-800/80 text-slate-400 border border-slate-800 hover:bg-slate-800 hover:text-slate-200"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Search Input */}
      <div className="relative mb-3">
        <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-500" />
        <input
          type="text"
          placeholder="Filter evidence by keyword, port, or file..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-slate-800 bg-black/40 pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-cyan-500 focus:outline-none font-mono"
        />
      </div>

      {/* Evidence Items List */}
      <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-800 p-8 text-center text-xs text-slate-500 font-mono">
            No matching evidence found. Run an investigation to inspect container facts.
          </div>
        ) : (
          filtered.map((item, idx) => {
            const isExpanded = expandedIndex === idx;
            return (
              <div
                key={idx}
                className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-3 transition-colors hover:border-slate-700"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] font-mono font-semibold ${getTypeBadge(
                          item.type
                        )}`}
                      >
                        {item.type}
                      </span>
                      <span className="font-mono text-[11px] text-slate-400 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                        {item.source}
                      </span>
                      <span className="text-[11px] font-mono text-emerald-400">
                        {(item.confidence * 100).toFixed(0)}% Certainty
                      </span>
                    </div>
                    <p className="text-xs text-slate-200 font-medium leading-relaxed">
                      {item.summary}
                    </p>
                  </div>

                  {item.details && (
                    <button
                      onClick={() => setExpandedIndex(isExpanded ? null : idx)}
                      className="text-slate-400 hover:text-slate-200 p-1 cursor-pointer"
                      title={isExpanded ? "Collapse payload" : "Expand payload"}
                    >
                      {isExpanded ? (
                        <ChevronUp className="h-4 w-4" />
                      ) : (
                        <ChevronDown className="h-4 w-4" />
                      )}
                    </button>
                  )}
                </div>

                {/* Expanded Details JSON viewer */}
                {isExpanded && item.details && (
                  <div className="mt-3 pt-2.5 border-t border-slate-800/80">
                    <pre className="rounded bg-black/60 p-2.5 text-[11px] font-mono text-cyan-300 overflow-x-auto max-h-48">
                      {typeof item.details === "string"
                        ? item.details
                        : JSON.stringify(item.details, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
