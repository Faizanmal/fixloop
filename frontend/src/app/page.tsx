"use client";

import React, { useState, useEffect } from "react";
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
} from "lucide-react";

export default function Home() {
  // System Readiness & Scenarios
  const [readiness, setReadiness] = useState<SystemReadiness | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>(STATIC_SCENARIOS);
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
          setHistory((prev) => {
            const ids = new Set(prev.map((p) => p.id));
            const uniqueNew = recentRuns.filter((r) => !ids.has(r.id));
            const merged = [...prev, ...uniqueNew];
            return merged.slice(0, 10);
          });
        }
      } catch (err: unknown) {
        console.warn("Readiness probe warning:", err);
      }
    }

    void executeLoad();
    const interval = setInterval(() => {
      void executeLoad();
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
    setIsInvestigating(true);
    setErrorMessage(null);
    setDiagnosis(null);
    setPatchProposal(null);
    setVerificationReport(null);
    const startTime = performance.now();
    const effectiveTarget = targetServiceId || selectedScenarioId;
    const isCustom = Boolean(customLogs && customLogs.trim());

    try {
      // Step A: Run real diagnosis via FastAPI
      const result = await apiClient.runDiagnosis(effectiveTarget, customLogs);
      setDiagnosis(result);

      // Step B: If conclusive preset scenario, fetch real proposed patch diff from backend
      if (!isCustom && result.status === "diagnosis_available" && result.confidence >= 0.9) {
        const patch = await apiClient.fetchPatchProposal(effectiveTarget);
        if (patch) {
          setPatchProposal(patch);
        }
      }

      // Record in recent history
      const durationMs = Math.round(performance.now() - startTime);
      const newHistoryItem: InvestigationHistoryItem = {
        id: result.investigation_id || `RUN-${Date.now().toString().slice(-4)}`,
        scenarioName: effectiveTarget,
        status: result.status,
        confidence: result.confidence,
        durationMs,
        timestamp: new Date().toLocaleTimeString(),
        isSample: false,
      };
      setHistory((prev) => [newHistoryItem, ...prev].slice(0, 10));
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "An unexpected error occurred during diagnosis."
      );
    } finally {
      setIsInvestigating(false);
    }
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
      const report = await apiClient.runVerification(
        selectedScenarioId,
        userApproved
      );
      setVerificationReport(report);

      // Update history with verification outcome
      setHistory((prev) =>
        prev.map((item, idx) =>
          idx === 0
            ? {
                ...item,
                status: report.status,
                durationMs: item.durationMs + report.duration_ms,
              }
            : item
        )
      );
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
    setShowDemoNotification(true);
    setSelectedScenarioId("scenario_b_healthcheck_mismatch");
    setIsInvestigating(true);
    setErrorMessage(null);
    setDiagnosis(null);
    setPatchProposal(null);
    setVerificationReport(null);

    const startTime = performance.now();

    try {
      // Step 1: Run Diagnosis on Scenario B
      const diagResult = await apiClient.runDiagnosis(
        "scenario_b_healthcheck_mismatch"
      );
      setDiagnosis(diagResult);

      const durationMs = Math.round(performance.now() - startTime);
      setHistory((prev) =>
        [
          {
            id:
              diagResult.investigation_id ||
              `DEMO-${Date.now().toString().slice(-4)}`,
            scenarioName: "scenario_b_healthcheck_mismatch",
            status: diagResult.status,
            confidence: diagResult.confidence,
            durationMs,
            timestamp: new Date().toLocaleTimeString(),
            isSample: false,
          },
          ...prev,
        ].slice(0, 10)
      );

      // Step 2: Fetch Patch Proposal
      const patch = await apiClient.fetchPatchProposal(
        "scenario_b_healthcheck_mismatch"
      );
      if (patch) {
        setPatchProposal(patch);
      }

      // Step 3: Run Sandboxed Verification
      if (
        diagResult.status === "diagnosis_available" &&
        diagResult.confidence >= 0.9
      ) {
        setIsVerifying(true);
        const verifyResult = await apiClient.runVerification(
          "scenario_b_healthcheck_mismatch",
          true
        );
        setVerificationReport(verifyResult);
      }
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error ? err.message : "Demo execution failed."
      );
    } finally {
      setIsInvestigating(false);
      setIsVerifying(false);
    }
  };

  const handleSelectHistoryItem = (item: InvestigationHistoryItem) => {
    setSelectedScenarioId(item.scenarioName);
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
          selectedScenario={selectedScenarioId}
          onSelectScenario={(id) => {
            setSelectedScenarioId(id);
            setDiagnosis(null);
            setPatchProposal(null);
            setVerificationReport(null);
          }}
          onStartInvestigation={() => handleStartInvestigation()}
          onCustomDiagnose={handleCustomDiagnose}
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
        {diagnosis && (
          <>
            {/* Hypotheses & Calibrated Confidence */}
            <HypothesesList
              diagnosis={diagnosis}
              onProceedToPatch={() => {
                const el = document.getElementById("patch-review-section");
                el?.scrollIntoView({ behavior: "smooth" });
              }}
              canPatch={canPatch}
            />

            {/* Collected Empirical Evidence */}
            <EvidenceViewer evidence={diagnosis.evidence} />

            {/* Patch Review Section (Only when empirical evidence threshold is met) */}
            {canPatch && (
              <div id="patch-review-section" className="mt-8">
                <PatchReviewCard
                  patchDiff={
                    patchProposal?.diff_unified ||
                    verificationReport?.patch_diff ||
                    (selectedScenarioId.includes("scenario_a")
                      ? `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -7,6 +7,7 @@\n     ports:\n       - "8080:8080"\n     environment:\n+      - DATABASE_URL=postgresql://app_user:app_pass@localhost:5432/app_db\n       - PORT=8080\n       - LOG_LEVEL=debug`
                      : selectedScenarioId.includes("scenario_b")
                      ? `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -10,3 +10,3 @@\n     healthcheck:\n-      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]\n+      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]`
                      : `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -8,2 +8,2 @@\n     ports:\n-      - "8000:5000"\n+      - "8000:8000"`)
                  }
                  targetFile={
                    patchProposal?.target_file ||
                    verificationReport?.target_file ||
                    "docker-compose.yml"
                  }
                  explanation={patchProposal?.explanation}
                  verificationProcedure={
                    patchProposal?.verification_procedure ||
                    (selectedScenarioId.includes("scenario_a")
                      ? "verify_env_presence"
                      : selectedScenarioId.includes("scenario_b")
                      ? "verify_healthcheck_endpoint"
                      : "verify_port_mapping")
                  }
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
            )}

            {/* Verification Report Card */}
            {verificationReport && (
              <VerificationReportCard
                report={verificationReport}
                scenarioName={selectedScenarioId}
                onRetry={() => handleApproveAndVerify(true)}
                isVerifying={isVerifying}
              />
            )}
          </>
        )}

        {/* 5. Recent Investigations History */}
        <RecentInvestigations
          history={history}
          onSelectHistoryItem={handleSelectHistoryItem}
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
