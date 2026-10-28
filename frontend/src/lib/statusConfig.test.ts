import assert from "node:assert";
import test from "node:test";
import { getStatusPanelConfig, type VerificationReportLike } from "./statusConfig";

test("verified_fixed status yields verified badge and next step to review/apply patch", () => {
  const dummyReport: VerificationReportLike = {
    status: "verified_fixed",
    test_output: "Container passed healthcheck with exit code 0",
  };

  const config = getStatusPanelConfig("verified_fixed", dummyReport, 0.98);
  assert.strictEqual(config.badgeText, "VERIFIED FIXED");
  assert.match(config.headline, /Verified.*Validated/i);
  assert.strictEqual(config.nextActionText, "Review and apply the patch");
  assert.strictEqual(config.isVerified, true);
  assert.strictEqual(config.isConclusive, true);
});

test("insufficient_evidence status yields matching headline and collection next step", () => {
  const config = getStatusPanelConfig("insufficient_evidence", null, 0.4);
  assert.strictEqual(config.badgeText, "INSUFFICIENT EVIDENCE");
  assert.strictEqual(config.headline, "Insufficient Empirical Evidence");
  assert.strictEqual(
    config.nextActionText,
    "Collect additional container logs or telemetry"
  );
  assert.strictEqual(config.isInsufficient, true);
  assert.strictEqual(config.isConclusive, false);
});

test("patch_blocked status triggers when confidence is below 0.90", () => {
  const config = getStatusPanelConfig("diagnosis_available", null, 0.75);
  assert.strictEqual(config.badgeText, "PATCH BLOCKED");
  assert.strictEqual(
    config.headline,
    "Patch Blocked (Safety Invariant Enforced)"
  );
  assert.strictEqual(
    config.nextActionText,
    "Inspect conflicting hypotheses and gather distinguishing probes"
  );
  assert.strictEqual(config.isConclusive, false);
});

test("verification_failed status displays sandbox failure headline and refinement next step", () => {
  const failedReport: VerificationReportLike = {
    status: "verification_failed",
    test_output: "Container exited with code 1: AssertionError",
    failure_evidence: "AssertionError: expected 200 got 500",
  };

  const config = getStatusPanelConfig("verification_failed", failedReport, 0.95);
  assert.strictEqual(config.badgeText, "VERIFICATION FAILED");
  assert.strictEqual(config.headline, "Patch Verification Failed in Sandbox");
  assert.strictEqual(
    config.nextActionText,
    "Refine hypothesis or formulate alternative patch"
  );
  assert.strictEqual(config.isVerified, false);
});

test("diagnosis_available status with high confidence indicates sandbox verify next step", () => {
  const config = getStatusPanelConfig("diagnosis_available", null, 0.95);
  assert.strictEqual(config.badgeText, "DIAGNOSIS AVAILABLE");
  assert.strictEqual(
    config.headline,
    "Root-Cause Hypotheses & Confidence Calibration"
  );
  assert.strictEqual(
    config.nextActionText,
    "Review patch and verify in sandbox"
  );
  assert.strictEqual(config.isConclusive, true);
});
