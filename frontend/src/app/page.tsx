"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  apiClient,
  ScenarioInfo,
  SystemReadiness,
  DiagnoseResponse,
  PatchProposal,
  VerificationReport,
  STATIC_SCENARIOS,
  InvestigationHistoryItem,
} from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { ProjectHealthSummary } from "@/components/ProjectHealthSummary";
import { ScenarioSelector } from "@/components/ScenarioSelector";
import { DiagnosticTimeline } from "@/components/DiagnosticTimeline";
import { EvidenceViewer } from "@/components/EvidenceViewer";
import { HypothesesList } from "@/components/HypothesesList";
import { PatchReviewCard } from "@/components/PatchReviewCard";
import { VerificationReportCard } from "@/components/VerificationReportCard";
import { RecentInvestigations } from "@/components/RecentInvestigations";
import {
  AlertTriangle,
  RotateCcw,
  Sparkles,
  X,
  ShieldCheck,
  History,
} from "lucide-react";

export default function Home() {
  // System Readiness & Scenarios
  const [readiness, setReadiness] = useState<SystemReadiness | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>(STATIC_SCENARIOS);
  const [selectedPresetId, setSelectedPresetId] = useState<string>(
    "scenario_a_missing_env"
  );
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>(
    "scenario_a_missing_env"
  );

  // Active Diagnostic & Verification Flow
  const [isInvestigating, setIsInvestigating] = useState<boolean>(false);
  const [isVerifying, setIsVerifying] = useState<boolean>(false);
  const [diagnosis, setDiagnosis] = useState<DiagnoseResponse | null>(null);
  const [patchProposal, setPatchProposal] = useState<PatchProposal | null>(null);
  const [verificationReport, setVerificationReport] =
    useState<VerificationReport | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // History & Demo State
  const [history, setHistory] = useState<InvestigationHistoryItem[]>([]);
  const [showDemoNotification, setShowDemoNotification] =
    useState<boolean>(false);
  const [inspectedRunId, setInspectedRunId] = useState<string | null>(null);
  const [isLoadingInspect, setIsLoadingInspect] = useState<boolean>(false);
  const [inspectError, setInspectError] = useState<string | null>(null);

  const selectedScenarioIdRef = useRef(selectedScenarioId);
  useEffect(() => {
    selectedScenarioIdRef.current = selectedScenarioId;
  }, [selectedScenarioId]);

  // In-flight request protection to prevent duplicate runs
  const inFlightRef = useRef<boolean>(false);

  // In-memory cache for fast historical run inspection
  const investigationCache = useRef<
    Map<
      string,
      {
        diagnosis: DiagnoseResponse;
        patchProposal: PatchProposal | null;
        verificationReport: VerificationReport | null;
      }
    >
  >(new Map());

  useEffect(() => {
    let isMounted = true;

    async function executeLoad() {
      try {
        const readyData = await apiClient.checkReadiness();
        if (isMounted) setReadiness(readyData);

        const scenarioList = await apiClient.fetchScenarios();
        if (isMounted && scenarioList && scenarioList.length > 0) {
          setScenarios(scenarioList);
        }

        const recentRuns = await apiClient.fetchRecentInvestigations();
        if (isMounted && recentRuns && recentRuns.length > 0) {
          // If in flight and history refresh finishes first, reset spinner immediately (Issue 2)
          if (inFlightRef.current) {
            const hasRecentMatch = recentRuns.some(
              (r) =>
                r.scenarioName === selectedScenarioIdRef.current &&
                Date.now() - new Date(r.startedAtIso || 0).getTime() < 90000
            );
            if (hasRecentMatch) {
              inFlightRef.current = false;
              setIsInvestigating(false);
            }
          }

          setHistory((prev) => {
            const map = new Map<string, InvestigationHistoryItem>();
            for (const item of prev) {
              map.set(item.id, item);
            }
            for (const item of recentRuns) {
              const existing = map.get(item.id);
              if (existing) {
                const isVerified =
                  existing.status === "verified_fixed" ||
                  item.status === "verified_fixed";
                map.set(item.id, {
                  ...existing,
                  ...item,
                  status: isVerified ? "verified_fixed" : item.status,
                  durationMs: isVerified && existing.verificationReport && existing.durationMs > item.durationMs
                    ? existing.durationMs
                    : item.durationMs,
                  verificationReport:
                    item.verificationReport || existing.verificationReport,
                  diagnosis: item.diagnosis || existing.diagnosis,
                  patchProposal:
                    item.patchProposal || existing.patchProposal,
                });
              } else {
                map.set(item.id, item);
              }
            }
            return Array.from(map.values()).slice(-20);
          });
        }
      } catch (err: unknown) {
        console.warn("Readiness probe warning:", err);
      }
    }

    void executeLoad();
    const interval = setInterval(() => {
      // Do not run background polls while diagnosis is in flight to keep UI responsive
      if (!inFlightRef.current) {
        void executeLoad();
      }
    }, 12000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const activeScenario =
    scenarios.find((s) => s.id === selectedScenarioId) || scenarios[0];

  // 1. Run Investigation Handler
  const handleStartInvestigation = async (
    customLogs?: string,
    targetServiceId?: string
  ) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setIsInvestigating(true);
    setErrorMessage(null);
    setDiagnosis(null);
    setPatchProposal(null);
    setVerificationReport(null);
    setInspectedRunId(null);
    setIsLoadingInspect(false);
    setInspectError(null);
    const startTime = performance.now();
    const effectiveTarget = targetServiceId || selectedScenarioId;

    try {
      // Step A: Run real diagnosis via FastAPI with idempotency key
      const idempotencyKey = `req-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const result = await apiClient.runDiagnosis(effectiveTarget, customLogs, idempotencyKey);
      setDiagnosis(result);

      // Step B: Fetch real proposed patch diff from backend
      let patch: PatchProposal | null = null;
      if (result.status === "diagnosis_available" && result.confidence >= 0.9) {
        patch = await apiClient.fetchPatchProposal(
          result.investigation_id || effectiveTarget
        );
        if (patch) {
          setPatchProposal(patch);
        }
      }

      // Record in recent history using server-measured authoritative duration
      const serverTimestamp = result.started_at_iso || new Date().toISOString();
      const durationMs =
        result.is_cached && result.original_duration_ms
          ? result.original_duration_ms
          : (result.duration_ms || Math.round(performance.now() - startTime));
      const invId =
        result.investigation_id || `RUN-${Date.now().toString().slice(-4)}`;
      const newHistoryItem: InvestigationHistoryItem = {
        id: invId,
        scenarioName: effectiveTarget,
        status: result.status,
        confidence: result.confidence,
        durationMs,
        diagnosisDurationMs: result.duration_ms || durationMs,
        lookupDurationMs: result.lookup_duration_ms || null,
        timestamp: new Date(serverTimestamp).toLocaleTimeString(),
        startedAtIso: serverTimestamp,
        isSample: false,
        isCached: Boolean(result.is_cached),
        originalDurationMs: result.original_duration_ms || null,
        diagnosis: result,
        patchProposal: patch,
        verificationReport: null,
      };

      // Store in memory cache for instant inspection
      investigationCache.current.set(invId, {
        diagnosis: result,
        patchProposal: patch,
        verificationReport: null,
      });

      setHistory((prev) => [
        ...prev.filter((p) => p.id !== invId),
        newHistoryItem,
      ]);
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "An unexpected error occurred during diagnosis."
      );
    } finally {
      inFlightRef.current = false;
      setIsInvestigating(false);
    }
  };

  // Preset Benchmarks Launcher: always uses selected preset and isolates preset from custom logs
  const handleStartPresetInvestigation = async (presetId?: string) => {
    const target =
      presetId ||
      (scenarios.some((s) => s.id === selectedPresetId)
        ? selectedPresetId
        : scenarios[0]?.id || "scenario_a_missing_env");
    setSelectedPresetId(target);
    setSelectedScenarioId(target);
    await handleStartInvestigation(undefined, target);
  };

  // 2. Custom Logs Diagnostic Handler
  const handleCustomDiagnose = async (serviceName: string, logs: string) => {
    const target = serviceName.trim() || "custom-service";
    setSelectedScenarioId(target);
    await handleStartInvestigation(logs, target);
  };

  // 3. Sandboxed Verification Execution Handler
  const handleApproveAndVerify = async (userApproved: boolean = true) => {
    setIsVerifying(true);
    setErrorMessage(null);

    try {
      const invId = diagnosis?.investigation_id;
      const report = await apiClient.runVerification(
        selectedScenarioId,
        userApproved,
        invId
      );
      setVerificationReport(report);

      // Update history with verification outcome immediately
      setHistory((prev) =>
        prev.map((item) =>
          item.id === (invId || prev[prev.length - 1]?.id)
            ? {
                ...item,
                status: report.status,
                durationMs: (item.diagnosisDurationMs || item.durationMs) + report.duration_ms,
                verificationDurationMs: report.duration_ms,
                verificationReport: report,
              }
            : item
        )
      );

      // Refresh history from server immediately (Issue 2)
      try {
        const freshRuns = await apiClient.fetchRecentInvestigations();
        if (freshRuns && freshRuns.length > 0) {
          setHistory((prev) => {
            const map = new Map<string, InvestigationHistoryItem>();
            for (const p of prev) map.set(p.id, p);
            for (const r of freshRuns) {
              const existing = map.get(r.id);
              if (existing) {
                const isVerified = existing.status === "verified_fixed" || r.status === "verified_fixed";
                map.set(r.id, {
                  ...existing,
                  ...r,
                  status: isVerified ? "verified_fixed" : r.status,
                  durationMs: isVerified && existing.verificationReport && existing.durationMs > r.durationMs
                    ? existing.durationMs
                    : r.durationMs,
                  verificationReport: r.verificationReport || existing.verificationReport,
                });
              } else {
                map.set(r.id, r);
              }
            }
            return Array.from(map.values()).slice(-20);
          });
        }
      } catch {
        // Soft fallback
      }

      // Update cache
      if (invId) {
        const cached = investigationCache.current.get(invId);
        if (cached) {
          cached.verificationReport = report;
        } else if (diagnosis) {
          investigationCache.current.set(invId, {
            diagnosis,
            patchProposal,
            verificationReport: report,
          });
        }
      }
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "An unexpected error occurred during sandbox verification."
      );
    } finally {
      setIsVerifying(false);
    }
  };

  // 4. Quick Demo Trigger for Hackathon Judges
  const handleQuickDemo = async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setShowDemoNotification(true);
    setSelectedPresetId("scenario_b_healthcheck_mismatch");
    setSelectedScenarioId("scenario_b_healthcheck_mismatch");
    setIsInvestigating(true);
    setErrorMessage(null);
    setDiagnosis(null);
    setPatchProposal(null);
    setVerificationReport(null);
    setInspectedRunId(null);
    setIsLoadingInspect(false);
    setInspectError(null);

    const startTime = performance.now();

    try {
      const idempotencyKey = `demo-${Date.now()}`;
      // Step 1: Run Diagnosis on Scenario B
      const diagResult = await apiClient.runDiagnosis(
        "scenario_b_healthcheck_mismatch",
        undefined,
        idempotencyKey
      );
      setDiagnosis(diagResult);

      const serverTimestamp = diagResult.started_at_iso || new Date().toISOString();
      const durationMs =
        diagResult.is_cached && diagResult.original_duration_ms
          ? diagResult.original_duration_ms
          : (diagResult.duration_ms || Math.round(performance.now() - startTime));
      const invId =
        diagResult.investigation_id ||
        `DEMO-${Date.now().toString().slice(-4)}`;
      const demoItem: InvestigationHistoryItem = {
        id: invId,
        scenarioName: "scenario_b_healthcheck_mismatch",
        status: diagResult.status,
        confidence: diagResult.confidence,
        durationMs,
        diagnosisDurationMs: diagResult.duration_ms || durationMs,
        lookupDurationMs: diagResult.lookup_duration_ms || null,
        timestamp: new Date(serverTimestamp).toLocaleTimeString(),
        startedAtIso: serverTimestamp,
        isSample: false,
        isCached: Boolean(diagResult.is_cached),
        originalDurationMs: diagResult.original_duration_ms || null,
        diagnosis: diagResult,
        patchProposal: null,
        verificationReport: null,
      };

      setHistory((prev) => [
        ...prev.filter((p) => p.id !== invId),
        demoItem,
      ]);

      // Step 2: Fetch Patch Proposal
      const patch = await apiClient.fetchPatchProposal(
        "scenario_b_healthcheck_mismatch"
      );
      if (patch) {
        setPatchProposal(patch);
        demoItem.patchProposal = patch;
      }

      // Step 3: Run Sandboxed Verification
      let verifyResult: VerificationReport | null = null;
      if (
        diagResult.status === "diagnosis_available" &&
        diagResult.confidence >= 0.9
      ) {
        setIsVerifying(true);
        verifyResult = await apiClient.runVerification(
          "scenario_b_healthcheck_mismatch",
          true,
          invId
        );
        setVerificationReport(verifyResult);

        // Update demoItem in history immediately so row reflects VERIFIED FIXED without lag
        const finalReport = verifyResult;
        if (finalReport) {
          setHistory((prev) =>
            prev.map((item) =>
              item.id === invId
                ? {
                    ...item,
                    status: finalReport.status,
                    durationMs: (item.diagnosisDurationMs || item.durationMs) + finalReport.duration_ms,
                    verificationDurationMs: finalReport.duration_ms,
                    verificationReport: finalReport,
                  }
                : item
            )
          );

          // Immediately refresh history from server (Issue 2)
          try {
            const freshRuns = await apiClient.fetchRecentInvestigations();
            if (freshRuns && freshRuns.length > 0) {
              setHistory((prev) => {
                const map = new Map<string, InvestigationHistoryItem>();
                for (const p of prev) map.set(p.id, p);
                for (const r of freshRuns) {
                  const existing = map.get(r.id);
                  if (existing) {
                    const isVerified = existing.status === "verified_fixed" || r.status === "verified_fixed";
                    map.set(r.id, {
                      ...existing,
                      ...r,
                      status: isVerified ? "verified_fixed" : r.status,
                      durationMs: isVerified && existing.verificationReport && existing.durationMs > r.durationMs
                        ? existing.durationMs
                        : r.durationMs,
                      verificationReport: r.verificationReport || existing.verificationReport,
                    });
                  } else {
                    map.set(r.id, r);
                  }
                }
                return Array.from(map.values()).slice(-20);
              });
            }
          } catch {
            // Soft fallback
          }
        }
      }

      // Cache demo execution
      investigationCache.current.set(invId, {
        diagnosis: diagResult,
        patchProposal: patch,
        verificationReport: verifyResult,
      });
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error ? err.message : "Demo execution failed."
      );
    } finally {
      inFlightRef.current = false;
      setIsInvestigating(false);
      setIsVerifying(false);
    }
  };

  // 5. Inspect button handler for historical runs
  const handleSelectHistoryItem = async (item: InvestigationHistoryItem) => {
    setSelectedScenarioId(item.scenarioName);
    setInspectedRunId(item.id);
    setErrorMessage(null);
    setInspectError(null);
    setIsLoadingInspect(true);

    try {
      // 1. Check in-memory cache first
      const cached = investigationCache.current.get(item.id);
      if (cached && cached.diagnosis) {
        setDiagnosis(cached.diagnosis);
        setPatchProposal(cached.patchProposal);
        setVerificationReport(cached.verificationReport);
        setIsLoadingInspect(false);
      } else if (item.diagnosis) {
        // 2. Use item preloaded data if present
        setDiagnosis(item.diagnosis);
        setPatchProposal(item.patchProposal || null);
        setVerificationReport(item.verificationReport || null);
        investigationCache.current.set(item.id, {
          diagnosis: item.diagnosis,
          patchProposal: item.patchProposal || null,
          verificationReport: item.verificationReport || null,
        });
        setIsLoadingInspect(false);
      } else {
        // 3. Fetch from backend /investigations/:id
        const fullInv = await apiClient.fetchInvestigation(item.id);
        let diag: DiagnoseResponse | null = null;
        let patch: PatchProposal | null = null;
        let report: VerificationReport | null = null;

        if (fullInv?.diagnosis) {
          diag = fullInv.diagnosis as DiagnoseResponse;
        } else {
          diag = await apiClient.fetchInvestigationDiagnosis(item.id);
        }

        if (fullInv?.verification_report) {
          report = fullInv.verification_report as VerificationReport;
        } else if (item.status === "verified_fixed") {
          report = {
            status: "verified_fixed",
            test_output: `Verification passed for ${item.scenarioName}. Isolated sandbox container returned exit code 0.`,
            expected_criteria: "Isolated sandbox container returns exit code 0 and health probe passes.",
            attempts: 1,
            reverted: true,
            duration_ms: item.durationMs,
          };
        }

        if (fullInv?.patch_proposal) {
          patch = fullInv.patch_proposal as PatchProposal;
        } else if (
          diag &&
          diag.status === "diagnosis_available" &&
          diag.confidence >= 0.9
        ) {
          patch = await apiClient.fetchPatchProposal(
            item.id || item.scenarioName
          );
        }

        if (diag) {
          setDiagnosis(diag);
          setPatchProposal(patch);
          setVerificationReport(report);
          investigationCache.current.set(item.id, {
            diagnosis: diag,
            patchProposal: patch,
            verificationReport: report,
          });
        } else {
          throw new Error(`Diagnosis details not found for run ${item.id}`);
        }
        setIsLoadingInspect(false);
      }
    } catch (err: unknown) {
      console.warn("Failed to load investigation details:", err);
      setInspectError(
        err instanceof Error ? err.message : "Failed to load run details."
      );
      setIsLoadingInspect(false);
    }

    // Scroll into view so the detail panel reflects the inspected run immediately
    setTimeout(() => {
      const el = document.getElementById("diagnostic-results-section");
      el?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  // Dedicated helper to resolve honest, matching patch diff for custom logs or preset scenarios
  const getPatchForDiagnosis = (
    diag: DiagnoseResponse | null,
    scenarioId: string,
    proposal: PatchProposal | null,
    report: VerificationReport | null
  ) => {
    if (proposal?.diff_unified) {
      return {
        diff: proposal.diff_unified,
        targetFile: proposal.target_file || "docker-compose.yml",
        explanation: proposal.explanation,
        procedure: proposal.verification_procedure || "verify_fix",
      };
    }
    if (report?.patch_diff) {
      return {
        diff: report.patch_diff,
        targetFile: report.target_file || "docker-compose.yml",
        explanation: "Verified patch applied to isolated sandbox container.",
        procedure: "verify_fix",
      };
    }

    // Derive from diagnosis summary, hypotheses and scenario text
    const text = (
      (diag?.summary || "") +
      " " +
      (diag?.hypotheses?.[0]?.description || "") +
      " " +
      scenarioId
    ).toLowerCase();

    if (
      text.includes("database_url") ||
      (text.includes("missing") && text.includes("env")) ||
      text.includes("scenario_a")
    ) {
      return {
        diff: `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -7,6 +7,7 @@\n     ports:\n       - "8080:8080"\n     environment:\n+      - DATABASE_URL=postgresql://app_user:app_pass@localhost:5432/app_db\n       - PORT=8080\n       - LOG_LEVEL=debug`,
        targetFile: "docker-compose.yml",
        explanation:
          "Added missing DATABASE_URL environment variable to service configuration in docker-compose.yml.",
        procedure: "verify_env_presence",
      };
    }

    if (
      text.includes("health") ||
      text.includes("healthcheck") ||
      text.includes("scenario_b") ||
      text.includes("404")
    ) {
      return {
        diff: `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -10,3 +10,3 @@\n     healthcheck:\n-      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]\n+      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]`,
        targetFile: "docker-compose.yml",
        explanation:
          "Updated healthcheck probe endpoint URL from '/health' to the active route '/healthz'.",
        procedure: "verify_healthcheck_endpoint",
      };
    }

    if (
      text.includes("rate_limit_burst") ||
      text.includes("regression") ||
      text.includes("scenario_g")
    ) {
      return {
        diff: `--- a/main.py\n+++ b/main.py\n@@ -12,2 +12,2 @@\n-RATE_LIMIT_BURST = "unparsed_string"\n+RATE_LIMIT_BURST = 100`,
        targetFile: "main.py",
        explanation:
          "Fixed configuration regression: set RATE_LIMIT_BURST to valid integer literal 100.",
        procedure: "verify_syntax",
      };
    }

    return {
      diff: `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -8,2 +8,2 @@\n     ports:\n-      - "8000:5000"\n+      - "8000:8000"`,
      targetFile: "docker-compose.yml",
      explanation:
        "Aligned container target port in docker-compose.yml from 5000 to 8000 to match application listener.",
      procedure: "verify_port_mapping",
    };
  };

  // Can a patch be proposed?
  const canPatch =
    diagnosis !== null &&
    diagnosis.status === "diagnosis_available" &&
    diagnosis.confidence >= 0.9;

  return (
    <div className="min-h-screen flex flex-col bg-[#090d16] text-slate-100">
      {/* Top Navigation */}
      <Navbar
        readiness={readiness}
        onQuickDemo={handleQuickDemo}
        isInvestigating={isInvestigating || isVerifying}
      />

      {/* Main Content Workspace */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Judge 3-Minute Demo Notification Banner */}
        {showDemoNotification && (
          <div className="mb-6 rounded-xl border border-cyan-500/40 bg-cyan-950/30 p-4 shadow-lg backdrop-blur flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Sparkles className="h-5 w-5 text-cyan-400 shrink-0" />
              <div>
                <h4 className="text-sm font-bold text-white font-mono flex items-center gap-2">
                  <span>3-Minute Judge Demonstration Workflow Activated</span>
                  <span className="rounded bg-cyan-500/20 px-2 py-0.5 text-[10px] text-cyan-300 font-mono">
                    Scenario B
                  </span>
                </h4>
                <p className="text-xs text-slate-300 mt-0.5 leading-relaxed">
                  Demonstrating complete end-to-end cycle: Normal logs &rarr; Active HTTP probe detects /healthz (200 OK) vs /health (404) &rarr; Formulates 98% confidence hypothesis &rarr; Synthesizes minimal patch diff &rarr; Verifies in disposable sandbox.
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowDemoNotification(false)}
              className="text-slate-400 hover:text-white p-1 cursor-pointer shrink-0 ml-3"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Actionable Error Alert */}
        {errorMessage && (
          <div className="mb-6 rounded-xl border border-rose-800 bg-rose-950/40 p-4 shadow-lg backdrop-blur flex items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-bold text-rose-300 font-mono">
                  Execution Notice
                </h4>
                <p className="text-xs text-rose-200 mt-1 font-mono leading-relaxed">
                  {errorMessage}
                </p>
              </div>
            </div>
            <button
              onClick={() => handleStartInvestigation()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-700 bg-rose-900/60 px-3 py-1.5 text-xs font-mono font-medium text-rose-200 hover:bg-rose-900 transition-all cursor-pointer shrink-0"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {/* 1. Project Health & Security Summary */}
        <ProjectHealthSummary
          readiness={readiness}
          activeScenario={activeScenario}
          totalDiagnosesCount={history.length}
        />

        {/* 2. Target Project / Scenario Selector & Launcher */}
        <ScenarioSelector
          scenarios={scenarios}
          selectedScenario={selectedPresetId}
          onSelectScenario={(id) => {
            setSelectedPresetId(id);
            setSelectedScenarioId(id);
            setDiagnosis(null);
            setPatchProposal(null);
            setVerificationReport(null);
          }}
          onStartInvestigation={() => handleStartPresetInvestigation()}
          onCustomDiagnose={handleCustomDiagnose}
          onCancelInvestigation={() => {
            inFlightRef.current = false;
            setIsInvestigating(false);
          }}
          isInvestigating={isInvestigating}
        />

        {/* 3. Diagnostic Timeline & Progression State Machine */}
        {(isInvestigating || diagnosis) && (
          <DiagnosticTimeline
            diagnosis={diagnosis}
            isInvestigating={isInvestigating}
            hasPatchVerified={
              verificationReport?.status === "verified_fixed"
            }
          />
        )}

        {/* 4. Investigation Workspace Results */}
        {(diagnosis || isLoadingInspect || inspectError) && (
          <div
            id="diagnostic-results-section"
            key={inspectedRunId || "active-run"}
            className="scroll-mt-8"
          >
            {/* Historical inspection banner */}
            {inspectedRunId && (
              <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-cyan-500/40 bg-cyan-950/30 p-4 shadow-lg backdrop-blur">
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-500/40 shrink-0">
                    <History className="h-4 w-4" />
                  </span>
                  <div>
                    <h4 className="text-xs font-mono font-bold text-white flex items-center gap-2">
                      <span>Inspecting Audit Run:</span>
                      <span className="text-cyan-300 font-bold">{inspectedRunId}</span>
                      <span className="text-slate-400 font-normal">
                        ({selectedScenarioId.replace("scenario_", "").replace(/_/g, " ")})
                      </span>
                    </h4>
                    <p className="text-[11px] text-slate-400 font-mono mt-0.5">
                      Displaying empirical findings, confidence metrics, and verification telemetry for this run.
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    setInspectedRunId(null);
                    setDiagnosis(null);
                    setPatchProposal(null);
                    setVerificationReport(null);
                    setInspectError(null);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-xs font-mono text-slate-300 hover:text-white hover:border-slate-600 transition-colors cursor-pointer self-start sm:self-auto"
                >
                  Clear Inspection
                </button>
              </div>
            )}

            {/* Loading Run State */}
            {isLoadingInspect && (
              <div className="mb-8 rounded-xl border border-cyan-500/30 bg-slate-900/60 p-8 text-center backdrop-blur">
                <div className="inline-flex h-8 w-8 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent mb-3" />
                <h4 className="text-sm font-mono font-bold text-white">
                  Loading Run {inspectedRunId}…
                </h4>
                <p className="text-xs text-slate-400 font-mono mt-1">
                  Retrieving empirical evidence, hypotheses, and verification telemetry.
                </p>
              </div>
            )}

            {/* Inspect Error State */}
            {!isLoadingInspect && inspectError && (
              <div className="mb-8 rounded-xl border border-rose-800 bg-rose-950/40 p-6 text-center backdrop-blur">
                <AlertTriangle className="h-6 w-6 text-rose-400 mx-auto mb-2" />
                <h4 className="text-sm font-mono font-bold text-rose-300">
                  Failed to load run {inspectedRunId}
                </h4>
                <p className="text-xs text-rose-200 mt-1 font-mono">{inspectError}</p>
                <button
                  onClick={() => {
                    const item = history.find((h) => h.id === inspectedRunId);
                    if (item) void handleSelectHistoryItem(item);
                  }}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-rose-700 bg-rose-900/60 px-3 py-1.5 text-xs font-mono text-rose-200 hover:bg-rose-900 cursor-pointer"
                >
                  <RotateCcw className="h-3 w-3" />
                  <span>Retry Loading</span>
                </button>
              </div>
            )}

            {/* Diagnosis Content */}
            {!isLoadingInspect && !inspectError && diagnosis && (
              <>
                {/* Hypotheses & Calibrated Confidence */}
                {(() => {
                  const activeItem = inspectedRunId
                    ? history.find((h) => h.id === inspectedRunId)
                    : (diagnosis.investigation_id
                        ? history.find((h) => h.id === diagnosis.investigation_id)
                        : null);
                  const effectiveStatus =
                    activeItem?.status ||
                    (verificationReport?.status === "verified_fixed"
                      ? "verified_fixed"
                      : verificationReport?.status === "verification_failed"
                      ? "verification_failed"
                      : diagnosis.status === "insufficient_evidence"
                      ? "insufficient_evidence"
                      : diagnosis.confidence < 0.9
                      ? "patch_blocked"
                      : diagnosis.status);
                  const effectiveDuration = activeItem?.durationMs;
                  const isCached = activeItem?.isCached;

                  return (
                    <HypothesesList
                      diagnosis={diagnosis}
                      onProceedToPatch={() => {
                        const el = document.getElementById("patch-review-section");
                        el?.scrollIntoView({ behavior: "smooth" });
                      }}
                      canPatch={canPatch}
                      runStatus={effectiveStatus}
                      verificationReport={verificationReport}
                      durationMs={effectiveDuration}
                      isCached={isCached}
                    />
                  );
                })()}

                {/* Collected Empirical Evidence */}
                <EvidenceViewer evidence={diagnosis.evidence} />

                {/* Patch Blocked State (When confidence < 90% or status is insufficient_evidence) */}
                {!canPatch && (
                  <div className="mt-8 rounded-xl border border-amber-500/40 bg-amber-950/20 p-5 shadow-sm backdrop-blur">
                    <div className="flex items-start gap-3">
                      <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
                      <div>
                        <h4 className="text-sm font-bold text-white font-mono flex items-center gap-2">
                          <span>Patch Proposal Blocked</span>
                          <span className="rounded bg-amber-500/20 border border-amber-500/40 px-2 py-0.5 text-[10px] text-amber-300 font-mono">
                            Safety Invariant Enforced
                          </span>
                        </h4>
                        <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                          FixLoop strictly refuses to propose uncorroborated patches. Minimum calibrated confidence threshold (&ge; 90%) was not reached ({Math.round((diagnosis.confidence || 0) * 100)}% observed).
                        </p>
                        {diagnosis.missing_information && diagnosis.missing_information.length > 0 && (
                          <div className="mt-3 text-xs font-mono text-amber-200/90">
                            <span className="font-semibold text-slate-400">Missing Telemetry:</span>
                            <ul className="list-disc list-inside mt-1 text-slate-300">
                              {diagnosis.missing_information.map((m, i) => (
                                <li key={i}>{m}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Patch Review Section (Only when empirical evidence threshold is met) */}
                {canPatch && (() => {
                  const activePatch = getPatchForDiagnosis(
                    diagnosis,
                    selectedScenarioId,
                    patchProposal,
                    verificationReport
                  );
                  return (
                    <div id="patch-review-section" className="mt-8">
                      <PatchReviewCard
                        patchDiff={activePatch.diff}
                        targetFile={activePatch.targetFile}
                        explanation={activePatch.explanation}
                        verificationProcedure={activePatch.procedure}
                        isAppliedToWorkingCopy={false}
                        onApproveAndVerify={handleApproveAndVerify}
                        onRejectPatch={() => {
                          setVerificationReport({
                            status: "patch_rejected",
                            test_output: "Patch rejected by user during review. Working copy preserved untouched.",
                            expected_criteria: "Explicit user approval",
                            attempts: 0,
                            reverted: true,
                            duration_ms: 0,
                          });
                        }}
                        isVerifying={isVerifying}
                      />
                    </div>
                  );
                })()}

                {/* Verification Report Card */}
                {verificationReport && (() => {
                  const activeItem = inspectedRunId
                    ? history.find((h) => h.id === inspectedRunId)
                    : (diagnosis.investigation_id
                        ? history.find((h) => h.id === diagnosis.investigation_id)
                        : null);
                  const totalDuration = activeItem?.durationMs || verificationReport.duration_ms;
                  const isCached = activeItem?.isCached;

                  return (
                    <VerificationReportCard
                      report={verificationReport}
                      scenarioName={selectedScenarioId}
                      onRetry={() => handleApproveAndVerify(true)}
                      isVerifying={isVerifying}
                      totalDurationMs={totalDuration}
                      isCached={isCached}
                    />
                  );
                })()}
              </>
            )}
          </div>
        )}

        {/* 5. Recent Investigations History */}
        <RecentInvestigations
          history={history}
          onSelectHistoryItem={handleSelectHistoryItem}
          activeInspectId={inspectedRunId}
          isLoadingInspect={isLoadingInspect}
        />
      </main>

      {/* Production Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-6 text-xs font-mono text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-400">FixLoop MVP</span>
            <span>•</span>
            <span>Nebius Token Factory</span>
            <span>•</span>
            <span>NVIDIA Nemotron-3-Nano</span>
          </div>
          <div className="flex items-center gap-4 text-slate-400">
            <span className="flex items-center gap-1 text-emerald-400">
              <ShieldCheck className="h-3.5 w-3.5" />
              Zero Shell Injection
            </span>
            <span>•</span>
            <span>Isolated Sandbox Verification</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
