"use client";

import React, { useState, useEffect } from "react";
import {
  apiClient,
  ScenarioInfo,
  SystemReadiness,
  DiagnoseResponse,
  VerificationReport,
  STATIC_SCENARIOS,
} from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { ProjectHealthSummary } from "@/components/ProjectHealthSummary";
import { ScenarioSelector } from "@/components/ScenarioSelector";
import { DiagnosticTimeline } from "@/components/DiagnosticTimeline";
import { EvidenceViewer } from "@/components/EvidenceViewer";
import { HypothesesList } from "@/components/HypothesesList";
import { PatchReviewCard } from "@/components/PatchReviewCard";
import { VerificationReportCard } from "@/components/VerificationReportCard";
import {
  RecentInvestigations,
  InvestigationHistoryItem,
} from "@/components/RecentInvestigations";
import {
  AlertTriangle,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";

export default function Home() {
  // System State
  const [readiness, setReadiness] = useState<SystemReadiness | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>(STATIC_SCENARIOS);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>(
    "scenario_a_missing_env"
  );

  // Investigation & Verification State
  const [isInvestigating, setIsInvestigating] = useState<boolean>(false);
  const [isVerifying, setIsVerifying] = useState<boolean>(false);
  const [diagnosis, setDiagnosis] = useState<DiagnoseResponse | null>(null);
  const [verificationReport, setVerificationReport] =
    useState<VerificationReport | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // History & Demo State
  const [history, setHistory] = useState<InvestigationHistoryItem[]>([]);
  const [showDemoNotification, setShowDemoNotification] =
    useState<boolean>(false);

  // Load readiness and scenarios on mount
  useEffect(() => {
    let isMounted = true;

    async function loadInitialData() {
      try {
        const readyData = await apiClient.checkReadiness();
        if (isMounted) setReadiness(readyData);

        const scenarioList = await apiClient.fetchScenarios();
        if (isMounted && scenarioList.length > 0) {
          setScenarios(scenarioList);
        }
      } catch (err: unknown) {
        console.error("Failed to load initial readiness:", err);
      }
    }

    loadInitialData();
    const interval = setInterval(loadInitialData, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const activeScenario =
    scenarios.find((s) => s.id === selectedScenarioId) || scenarios[0];

  // 1. Run Investigation Handler
  const handleStartInvestigation = async () => {
    setIsInvestigating(true);
    setErrorMessage(null);
    setVerificationReport(null);
    const startTime = performance.now();

    try {
      const result = await apiClient.runDiagnosis(selectedScenarioId);
      setDiagnosis(result);

      // Record in recent history
      const durationMs = Math.round(performance.now() - startTime);
      const newHistoryItem: InvestigationHistoryItem = {
        id: `RUN-${Date.now().toString().slice(-4)}`,
        scenarioName: selectedScenarioId,
        status: result.status,
        confidence: result.confidence,
        durationMs,
        timestamp: new Date().toLocaleTimeString(),
      };
      setHistory((prev) => [newHistoryItem, ...prev.slice(0, 9)]);
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

  // 2. Run Sandboxed Verification Handler
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
          : "An unexpected error occurred during verification."
      );
    } finally {
      setIsVerifying(false);
    }
  };

  // 3. Quick Demo Trigger for Hackathon Judges
  const handleQuickDemo = async () => {
    setShowDemoNotification(true);
    setSelectedScenarioId("scenario_b_healthcheck_mismatch");
    setIsInvestigating(true);
    setErrorMessage(null);
    setDiagnosis(null);
    setVerificationReport(null);

    const startTime = performance.now();

    try {
      // Step 1: Run Diagnosis
      const diagResult = await apiClient.runDiagnosis(
        "scenario_b_healthcheck_mismatch"
      );
      setDiagnosis(diagResult);

      const durationMs = Math.round(performance.now() - startTime);
      setHistory((prev) => [
        {
          id: `DEMO-${Date.now().toString().slice(-4)}`,
          scenarioName: "scenario_b_healthcheck_mismatch",
          status: diagResult.status,
          confidence: diagResult.confidence,
          durationMs,
          timestamp: new Date().toLocaleTimeString(),
        },
        ...prev.slice(0, 9),
      ]);

      // Step 2: Automatically verify in sandbox
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
    <div className="min-h-screen flex flex-col bg-[#090d16]">
      {/* Top Navigation */}
      <Navbar
        readiness={readiness}
        onQuickDemo={handleQuickDemo}
        isInvestigating={isInvestigating || isVerifying}
      />

      {/* Main Content Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Demo Mode Banner Notification */}
        {showDemoNotification && (
          <div className="mb-6 rounded-xl border border-cyan-500/40 bg-cyan-950/30 p-4 shadow-lg backdrop-blur flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Sparkles className="h-5 w-5 text-cyan-400 shrink-0" />
              <div>
                <h4 className="text-sm font-bold text-white font-mono">
                  3-Minute Judge Demo Workflow Activated
                </h4>
                <p className="text-xs text-slate-300">
                  Executing Scenario B (Normal logs + Healthcheck mismatch). Engine
                  executes HTTP probe, isolates port difference, proposes unified diff,
                  and validates in disposable sandbox.
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowDemoNotification(false)}
              className="text-slate-400 hover:text-white p-1 cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Error Alert with Retry */}
        {errorMessage && (
          <div className="mb-6 rounded-xl border border-rose-800 bg-rose-950/40 p-4 shadow-lg backdrop-blur flex items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-sm font-bold text-rose-300 font-mono">
                  Execution Notice
                </h4>
                <p className="text-xs text-rose-200 mt-1 font-mono">
                  {errorMessage}
                </p>
              </div>
            </div>
            <button
              onClick={handleStartInvestigation}
              className="inline-flex items-center gap-1.5 rounded-lg border border-rose-700 bg-rose-900/60 px-3 py-1.5 text-xs font-mono font-medium text-rose-200 hover:bg-rose-900 transition-all cursor-pointer shrink-0"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {/* Project Health & Limits Summary */}
        <ProjectHealthSummary
          readiness={readiness}
          activeScenario={activeScenario}
          totalDiagnosesCount={history.length}
        />

        {/* Scenario Selector & Investigation Launch */}
        <ScenarioSelector
          scenarios={scenarios}
          selectedScenario={selectedScenarioId}
          onSelectScenario={(id) => {
            setSelectedScenarioId(id);
            setDiagnosis(null);
            setVerificationReport(null);
          }}
          onStartInvestigation={handleStartInvestigation}
          isInvestigating={isInvestigating}
        />

        {/* Diagnostic Stepper & Timeline */}
        {(isInvestigating || diagnosis) && (
          <DiagnosticTimeline
            diagnosis={diagnosis}
            isInvestigating={isInvestigating}
            hasPatchVerified={
              verificationReport?.status === "verified_fixed"
            }
          />
        )}

        {/* Investigation Results Section */}
        {diagnosis && (
          <>
            {/* Hypotheses & Confidence Calibration */}
            <HypothesesList
              diagnosis={diagnosis}
              onProceedToPatch={() => {
                // Smooth scroll to patch review
                const el = document.getElementById("patch-review-section");
                el?.scrollIntoView({ behavior: "smooth" });
              }}
              canPatch={canPatch}
            />

            {/* Collected Empirical Evidence */}
            <EvidenceViewer evidence={diagnosis.evidence} />

            {/* Patch Review Section (Only for conclusive evidence) */}
            {canPatch && (
              <div id="patch-review-section" className="mt-8">
                <PatchReviewCard
                  patchDiff={
                    verificationReport?.patch_diff ||
                    (selectedScenarioId.includes("scenario_a")
                      ? `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -9,2 +9,3 @@\n     environment:\n+      - DATABASE_URL=postgresql://app_user:app_pass@localhost:5432/app_db\n       - PORT=8080`
                      : selectedScenarioId.includes("scenario_b")
                      ? `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -10,3 +10,3 @@\n     healthcheck:\n-      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]\n+      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]`
                      : `--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -8,2 +8,2 @@\n     ports:\n-      - "8000:5000"\n+      - "8000:8000"`)
                  }
                  targetFile={verificationReport?.target_file || "docker-compose.yml"}
                  onApproveAndVerify={handleApproveAndVerify}
                  onRejectPatch={() => {
                    setVerificationReport({
                      status: "patch_rejected",
                      test_output: "Patch rejected by developer during review.",
                      expected_criteria: "Developer approval",
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

        {/* Recent Investigations History */}
        <RecentInvestigations
          history={history}
          onSelectHistoryItem={handleSelectHistoryItem}
        />
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-6 text-center text-xs font-mono text-slate-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span>FixLoop Autonomous Debugging Engine • Powered by Nebius Token Factory & NVIDIA Models</span>
          <span className="text-slate-400">Zero Host Shell Exec • Isolated Sandbox Verification</span>
        </div>
      </footer>
    </div>
  );
}
