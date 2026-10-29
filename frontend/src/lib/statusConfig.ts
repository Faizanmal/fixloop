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
      : "Isolated sandbox container returned exit code 0";
    const testSummary = stripTrailingPeriod(rawSummary);

    return {
      badgeText: "VERIFIED FIXED",
      badgeClassName: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
      headline: "Root Cause Verified & Sandbox Fix Validated",
      nextActionText: "Review and apply the patch",
      detailMessage: `Sandbox verification passed: ${testSummary}. Fix validated and reverted to pristine state.`,
      isConclusive: true,
      isInsufficient: false,
      isVerified: true,
      isVerificationFailed: false,
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
      headline: "Patch Verification Failed in Sandbox",
      nextActionText: "Refine hypothesis or formulate alternative patch",
      detailMessage: verificationReport?.failure_evidence || "Test suite failed in disposable sandbox. Changes automatically reverted.",
      isConclusive: false,
      isInsufficient: false,
      isVerified: false,
      isVerificationFailed: true,
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
    };
  }

  // 5. Diagnosis Available
  return {
    badgeText: "DIAGNOSIS AVAILABLE",
    badgeClassName: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
    headline: "Root-Cause Hypotheses & Confidence Calibration",
    nextActionText: fallbackNextAction || "Review patch and verify in sandbox",
    detailMessage: "Empirical evidence corroborates root-cause hypothesis above 90% threshold.",
    isConclusive: true,
    isInsufficient: false,
    isVerified: false,
  };
}
