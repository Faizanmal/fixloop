"use client";

import React, { useState, useMemo } from "react";
import { EvidenceRecord } from "@/lib/api";
import {
  FileText,
  Search,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Terminal,
  Server,
  Layers,
  Code2,
  KeyRound,
  Activity,
  Maximize2,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

interface EvidenceViewerProps {
  evidence: EvidenceRecord[];
}

export function EvidenceViewer({ evidence }: EvidenceViewerProps) {
  const [filterCategory, setFilterCategory] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [modalItem, setModalItem] = useState<EvidenceRecord | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Categorize evidence item based on source string
  const categorizeItem = (item: EvidenceRecord): string => {
    const s = item.source.toLowerCase();
    if (s.includes("log")) return "LOGS";
    if (s.includes("inspect") || s.includes("docker:inspect")) return "DOCKER_STATE";
    if (s.includes("compose")) return "COMPOSE_CONFIG";
    if (s.includes("source") || s.includes("main.py") || s.includes("dockerfile")) return "SOURCE_CODE";
    if (s.includes("probe") || s.includes("tool:")) return "DIAGNOSTIC_PROBE";
    if (s.includes("env")) return "ENV_AUDIT";
    return "SYSTEM";
  };

  const categories = useMemo(() => {
    const catSet = new Set<string>(["ALL"]);
    evidence.forEach((e) => catSet.add(categorizeItem(e)));
    return Array.from(catSet);
  }, [evidence]);

  const filtered = useMemo(() => {
    return evidence.filter((item) => {
      const cat = categorizeItem(item);
      const matchesFilter = filterCategory === "ALL" || cat === filterCategory;
      const q = searchQuery.toLowerCase().trim();
      const matchesSearch =
        q === "" ||
        (item.content && item.content.toLowerCase().includes(q)) ||
        (item.source && item.source.toLowerCase().includes(q)) ||
        (item.id && item.id.toLowerCase().includes(q));
      return matchesFilter && matchesSearch;
    });
  }, [evidence, filterCategory, searchQuery]);

  const getCategoryBadge = (cat: string) => {
    switch (cat) {
      case "LOGS":
        return {
          icon: Terminal,
          badge: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
          label: "Container Logs",
        };
      case "DOCKER_STATE":
        return {
          icon: Server,
          badge: "bg-amber-500/10 text-amber-400 border-amber-500/30",
          label: "Docker State",
        };
      case "COMPOSE_CONFIG":
        return {
          icon: Layers,
          badge: "bg-indigo-500/10 text-indigo-400 border-indigo-500/30",
          label: "Compose Config",
        };
      case "SOURCE_CODE":
        return {
          icon: Code2,
          badge: "bg-teal-500/10 text-teal-400 border-teal-500/30",
          label: "Source Code",
        };
      case "DIAGNOSTIC_PROBE":
        return {
          icon: Activity,
          badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
          label: "Diagnostic Probe",
        };
      case "ENV_AUDIT":
        return {
          icon: KeyRound,
          badge: "bg-purple-500/10 text-purple-400 border-purple-500/30",
          label: "Environment Audit",
        };
      default:
        return {
          icon: FileText,
          badge: "bg-slate-800 text-slate-300 border-slate-700",
          label: "Observation",
        };
    }
  };

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // Helper to format content (detect JSON strings)
  const formatContent = (content: string) => {
    try {
      const parsed = JSON.parse(content);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return content;
    }
  };

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm backdrop-blur mb-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="rounded-full bg-cyan-500/10 border border-cyan-500/30 px-2.5 py-0.5 text-xs font-mono font-bold text-cyan-400">
              EMPIRICAL OBSERVATIONS
            </span>
            <span className="text-xs font-mono text-slate-400">
              {evidence.length} records captured
            </span>
          </div>
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <FileText className="h-4 w-4 text-cyan-400" />
            Collected Empirical Evidence & Probe Results
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Concrete facts collected from container exit codes, logs, listening ports, and allowlisted active probes.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-1.5">
          {categories.map((c) => {
            const meta = getCategoryBadge(c);
            const isSelected = filterCategory === c;
            return (
              <button
                key={c}
                onClick={() => setFilterCategory(c)}
                className={`rounded-lg px-2.5 py-1 text-[11px] font-mono font-medium transition-all cursor-pointer select-none ${
                  isSelected
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                    : "bg-slate-800/80 text-slate-400 border border-slate-800 hover:bg-slate-800 hover:text-slate-200"
                }`}
              >
                {c === "ALL" ? "All Facts" : meta.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Search Input */}
      <div className="relative mb-3">
        <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-500" />
        <input
          type="text"
          placeholder="Filter evidence by keyword, port, exit code, or source..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full rounded-lg border border-slate-800 bg-black/40 pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:border-cyan-500 focus:outline-none font-mono"
        />
      </div>

      {/* Evidence Items List */}
      <div className="space-y-2.5 max-h-[460px] overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-800 p-8 text-center text-xs text-slate-500 font-mono">
            No matching evidence found for query: &quot;{searchQuery}&quot;
          </div>
        ) : (
          filtered.map((item, idx) => {
            const cat = categorizeItem(item);
            const badgeMeta = getCategoryBadge(cat);
            const Icon = badgeMeta.icon;
            const isExpanded = expandedId === item.id;
            const formatted = formatContent(item.content);
            const isMultiline = formatted.includes("\n") || formatted.length > 120;

            return (
              <div
                key={item.id || idx}
                className="rounded-lg border border-slate-800/90 bg-slate-950/70 p-3.5 transition-colors hover:border-slate-700"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-mono font-semibold ${badgeMeta.badge}`}
                      >
                        <Icon className="h-3 w-3" />
                        {badgeMeta.label}
                      </span>
                      <span className="font-mono text-[11px] text-cyan-300 bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-800/50">
                        {item.id}
                      </span>
                      <span className="font-mono text-[11px] text-slate-400 bg-slate-900 px-2 py-0.5 rounded border border-slate-800 truncate max-w-[320px]" title={item.source}>
                        {item.source}
                      </span>
                      {item.timestamp && (
                        <span className="text-[10px] font-mono text-slate-500">
                          {new Date(item.timestamp).toLocaleTimeString()}
                        </span>
                      )}
                    </div>

                    {/* Preview Content */}
                    <div className="text-xs text-slate-200 font-mono leading-relaxed bg-black/40 rounded p-2.5 border border-slate-900 overflow-x-auto">
                      <pre className="whitespace-pre-wrap font-mono text-[11px] text-slate-300">
                        {isExpanded || !isMultiline
                          ? formatted
                          : formatted.slice(0, 150) + "..."}
                      </pre>
                    </div>
                  </div>

                  {/* Actions Column */}
                  <div className="flex items-center gap-1 shrink-0 pt-0.5">
                    <button
                      onClick={() => handleCopy(item.content, item.id)}
                      className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition-colors cursor-pointer"
                      title="Copy raw evidence content"
                    >
                      {copiedId === item.id ? (
                        <Check className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <Copy className="h-3.5 w-3.5" />
                      )}
                    </button>
                    <button
                      onClick={() => setModalItem(item)}
                      className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition-colors cursor-pointer"
                      title="Open full view modal"
                    >
                      <Maximize2 className="h-3.5 w-3.5" />
                    </button>
                    {isMultiline && (
                      <button
                        onClick={() => setExpandedId(isExpanded ? null : item.id)}
                        className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition-colors cursor-pointer"
                        title={isExpanded ? "Collapse preview" : "Expand preview"}
                      >
                        {isExpanded ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Full Modal Inspector */}
      {modalItem && (
        <Dialog open={!!modalItem} onOpenChange={() => setModalItem(null)}>
          <DialogContent onClose={() => setModalItem(null)} className="max-w-3xl">
            <DialogHeader>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-cyan-400 font-bold bg-cyan-950/40 px-2.5 py-0.5 rounded border border-cyan-800/60">
                  {modalItem.id}
                </span>
                <DialogTitle>Raw Evidence Payload Inspector</DialogTitle>
              </div>
              <p className="text-xs font-mono text-slate-400 mt-1">
                Source: {modalItem.source}
              </p>
            </DialogHeader>

            <div className="my-3 overflow-y-auto max-h-[60vh]">
              <pre className="rounded-lg bg-black/80 p-4 font-mono text-xs text-cyan-300 overflow-x-auto whitespace-pre-wrap border border-slate-800">
                {formatContent(modalItem.content)}
              </pre>
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-slate-800 text-xs font-mono">
              <span className="text-slate-500">
                Length: {modalItem.content.length} characters
              </span>
              <button
                onClick={() => handleCopy(modalItem.content, modalItem.id)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700 transition-colors cursor-pointer"
              >
                {copiedId === modalItem.id ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                    <span>Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    <span>Copy Raw Payload</span>
                  </>
                )}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
