import { stripTrailingPeriod } from "@/lib/utils";

export interface VerificationReportLike {
  status?: string;
  test_output?: string;
  failure_evidence?: string | null;
}

export interface StatusPanelConfig {
  badgeText: string;
  badgeClassName: string;
  headline: string;
  nextActionText: string;
  detailMessage?: string;
  isConclusive: boolean;
  isInsufficient: boolean;
  isVerified: boolean;
  isVerificationFailed?: boolean;
  isNoSafePatch?: boolean;
}

/**
 * Derives the Inspect panel's badge, headline, and next-action text
 * directly from the run's stored final status and verification telemetry.
 */
export function getStatusPanelConfig(
  status: string,
  verificationReport?: VerificationReportLike | null,
  confidence: number = 0.95,
  fallbackNextAction?: string
): StatusPanelConfig {
  const normStatus = (status || "").toLowerCase().trim();

  // 1. Verified Fixed status
  if (
    normStatus === "verified_fixed" ||
    normStatus === "verified_fix" ||
    normStatus === "verified" ||
    verificationReport?.status === "verified_fixed"
  ) {
    const rawSummary = verificationReport?.test_output
      ? verificationReport.test_output.split("\n")[0].trim()
      : "File-check verification returned exit code 0";
    const testSummary = stripTrailingPeriod(rawSummary);

    return {
      badgeText: "VERIFIED FIXED",
      badgeClassName: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
      headline: "Root Cause Verified & File-Check Fix Validated",
      nextActionText: "Review and apply the patch",
      detailMessage: `File-check verification passed: ${testSummary}. Fix validated in disposable workspace; host copy reverted.`,
      isConclusive: true,
      isInsufficient: false,
      isVerified: true,
      isVerificationFailed: false,
      isNoSafePatch: false,
    };
  }

  // 2. Insufficient Evidence status
  if (
    normStatus === "insufficient_evidence" ||
    normStatus === "insufficient"
  ) {
    return {
      badgeText: "INSUFFICIENT EVIDENCE",
      badgeClassName: "bg-purple-500/10 text-purple-400 border-purple-500/30",
      headline: "Insufficient Empirical Evidence",
      nextActionText: "Collect additional container logs or telemetry",
      detailMessage: "Engine refuses to fabricate patches without distinguishing empirical probes.",
      isConclusive: false,
      isInsufficient: true,
      isVerified: false,
      isVerificationFailed: false,
      isNoSafePatch: false,
    };
  }

  // 3. Verification Failed status
  if (
    normStatus === "verification_failed" ||
    normStatus === "failed_fix" ||
    normStatus === "patch_rejected" ||
    verificationReport?.status === "verification_failed" ||
    verificationReport?.status === "patch_rejected"
  ) {
    return {
      badgeText: "VERIFICATION FAILED",
      badgeClassName: "bg-rose-500/10 text-rose-400 border-rose-500/30",
      headline: "Patch Verification Failed (File-Check Mode)",
      nextActionText: "Refine hypothesis or formulate alternative patch",
      detailMessage: verificationReport?.failure_evidence || "Checks failed in disposable filesystem workspace. Changes automatically reverted.",
      isConclusive: false,
      isInsufficient: false,
      isVerified: false,
      isVerificationFailed: true,
      isNoSafePatch: false,
    };
  }

  // 4. Patch Blocked (Safety invariant enforced: confidence < 0.9 or low certainty)
  if (
    normStatus === "patch_blocked" ||
    confidence < 0.9
  ) {
    return {
      badgeText: "PATCH BLOCKED",
      badgeClassName: "bg-amber-500/10 text-amber-400 border-amber-500/30",
      headline: "Patch Blocked (Safety Invariant Enforced)",
      nextActionText: "Inspect conflicting hypotheses and gather distinguishing probes",
      detailMessage: `Calibrated confidence (${Math.round(confidence * 100)}%) is below the required 90% threshold. Automated patching strictly prevented.`,
      isConclusive: false,
      isInsufficient: false,
      isVerified: false,
      isVerificationFailed: false,
      isNoSafePatch: false,
    };
  }

  // 5. Diagnosis Available, No Safe Patch
  if (
    normStatus === "diagnosis_no_patch" ||
    normStatus === "no_safe_patch" ||
    normStatus.includes("no patch")
  ) {
    const patchedFallback =
      fallbackNextAction &&
      !/apply minimal configuration or code patch/i.test(fallbackNextAction)
        ? fallbackNextAction
        : "Manually investigate the diagnosed root cause; no automated safe patch is available";
    return {
      badgeText: "DIAGNOSIS AVAILABLE, NO PATCH",
      badgeClassName: "bg-amber-500/10 text-amber-400 border-amber-500/30",
      headline: "Diagnosis Available (No Safe Patch Available)",
      nextActionText: patchedFallback,
      detailMessage: "Root cause diagnosed, but no automated safe patch exists for this external dependency or infrastructure state.",
      isConclusive: true,
      isInsufficient: false,
      isVerified: false,
      isVerificationFailed: false,
      isNoSafePatch: true,
    };
  }

  // 6. Diagnosis Available
  return {
    badgeText: "DIAGNOSIS AVAILABLE",
    badgeClassName: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
    headline: "Root-Cause Hypotheses & Confidence Calibration",
    nextActionText: fallbackNextAction || "Review patch and verify in file-check mode",
    detailMessage: "Empirical evidence corroborates root-cause hypothesis above 90% threshold.",
    isConclusive: true,
    isInsufficient: false,
    isVerified: false,
    isVerificationFailed: false,
    isNoSafePatch: false,
  };
}
