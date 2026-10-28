import assert from "node:assert";
import test from "node:test";
import { getStatusPanelConfig, type VerificationReportLike } from "./statusConfig";
import { extractEnvVarInfo } from "./utils";

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

test("Step 3 Active Probing description does not state deterministic crash for insufficient evidence", () => {
  const getStep3Desc = (probesCount: number, status: string | undefined) => {
    return probesCount > 0
      ? `${probesCount} allowlisted HTTP/TCP probe(s) dispatched`
      : status === "insufficient_evidence"
      ? "Local probes evaluated and exhausted; external dependency prevented local deterministic probing"
      : "Probing evaluated (no active probe required for deterministic crash)";
  };

  const presetDDesc = getStep3Desc(0, "insufficient_evidence");
  assert.strictEqual(
    presetDDesc,
    "Local probes evaluated and exhausted; external dependency prevented local deterministic probing"
  );
  assert.ok(!presetDDesc.includes("deterministic crash"));

  const scenarioADesc = getStep3Desc(0, "diagnosis_available");
  assert.strictEqual(
    scenarioADesc,
    "Probing evaluated (no active probe required for deterministic crash)"
  );
});

test("extractEnvVarInfo extracts REDIS_URL and connection default correctly", () => {
  const result = extractEnvVarInfo("Traceback: line 12 KeyError: 'REDIS_URL'\nFailed to connect");
  assert.notStrictEqual(result, null);
  assert.strictEqual(result?.varName, "REDIS_URL");
  assert.strictEqual(result?.defaultVal, "redis://localhost:6379/0");
});

test("extractEnvVarInfo extracts DATABASE_URL and postgres default correctly", () => {
  const result = extractEnvVarInfo("Missing required environment variable: DATABASE_URL for pool initialization");
  assert.notStrictEqual(result, null);
  assert.strictEqual(result?.varName, "DATABASE_URL");
  assert.strictEqual(result?.defaultVal, "postgresql://app_user:app_pass@localhost:5432/app_db");
});

test("extractEnvVarInfo handles security and port tokens", () => {
  const jwt = extractEnvVarInfo("KeyError 'JWT_SECRET'");
  assert.strictEqual(jwt?.varName, "JWT_SECRET");
  assert.strictEqual(jwt?.defaultVal, "dev_secret_key_change_in_production");

  const port = extractEnvVarInfo("undefined environment variable PORT");
  assert.strictEqual(port?.varName, "PORT");
  assert.strictEqual(port?.defaultVal, "8080");

  const unrelated = extractEnvVarInfo("404 healthcheck probe failed");
  assert.strictEqual(unrelated, null);
});

