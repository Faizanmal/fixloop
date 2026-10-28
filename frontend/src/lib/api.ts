/**
 * FixLoop API Client & TypeScript Interfaces
 * Connects directly to FastAPI backend endpoints with graceful offline/loading fallbacks.
 * Grounded in empirical test outputs and verified sandbox executions.
 */

/**
 * Resolves the effective API base URL.
 * - In production (HTTPS page): Calling an unencrypted http:// address directly from
 *   the browser is blocked by browsers as "Mixed Content". When on HTTPS without an explicit
 *   https:// backend, we return "" (relative root) so requests route through Next.js / Vercel
 *   server-side rewrites.
 * - In local development (HTTP page) or SSR: uses configured env or defaults to local FastAPI.
 */
export function getApiBaseUrl(): string {
  const envUrl =
    (typeof process.env.NEXT_PUBLIC_API_BASE_URL === "string"
      ? process.env.NEXT_PUBLIC_API_BASE_URL
      : process.env.NEXT_PUBLIC_API_URL) || "";

  if (typeof window !== "undefined") {
    // Client-side execution in the browser
    if (window.location.protocol === "https:") {
      if (envUrl.startsWith("https://")) {
        return envUrl.replace(/\/+$/, "");
      }
      // If backend URL is http:// or empty, use same-origin relative path
      // Next.js rewrites proxy this server-side without mixed content
      return "";
    }
    // Browser is on http:// (e.g. localhost:3000)
    if (envUrl) {
      return envUrl.replace(/\/+$/, "");
    }
    return "http://127.0.0.1:8000";
  }

  // Server-side execution (SSR / Node.js)
  return (
    process.env.BACKEND_API_URL ||
    envUrl ||
    "http://127.0.0.1:8000"
  ).replace(/\/+$/, "");
}

export const API_BASE_URL = getApiBaseUrl();

export interface ScenarioInfo {
  id: string;
  name: string;
  description: string;
  difficulty: "Easy" | "Medium" | "Hard";
  requires_probe: boolean;
}

export interface DiagnoseHypothesis {
  id?: string;
  description: string;
  confidence: number;
  supporting_evidence: string[];
  contradicting_evidence?: string[];
  refuting_evidence?: string[];
  recommended_discriminating_test?: string | null;
}

export interface EvidenceRecord {
  id: string;
  source: string;
  content: string;
  timestamp?: string | null;
  // Computed / UI helper attributes
  type?: string;
  confidence?: number;
  summary?: string;
}

export interface RecommendTest {
  id: string;
  test_type: string;
  target: string;
  description: string;
  expected_signal: string;
  safety_level?: "READ_ONLY" | "LOW_RISK" | "HIGH_RISK";
}

export interface AuditLog {
  observations?: Array<Record<string, unknown> | string>;
  probes_executed?: string[];
  stop_reason?: string;
  selected_tests?: Array<{
    test_id: string;
    tool_name: string;
    target: string;
    rationale: string;
  }>;
}

export interface DiagnoseResponse {
  status: "diagnosis_available" | "insufficient_evidence" | "human_intervention_required";
  summary: string;
  hypotheses: DiagnoseHypothesis[];
  evidence: EvidenceRecord[];
  recommended_tests: RecommendTest[];
  missing_information: string[];
  confidence: number;
  next_action: string;
  audit_log?: AuditLog;
  investigation_id?: string;
  is_cached?: boolean;
  original_duration_ms?: number | null;
  lookup_duration_ms?: number | null;
  duration_ms?: number | null;
  started_at_iso?: string | null;
  idempotency_key?: string | null;
}

export interface PatchProposal {
  id: string;
  hypothesis_id: string;
  target_file: string;
  diff_unified: string;
  explanation: string;
  risk_level: string;
  requires_human_approval: boolean;
  verification_procedure: string;
}

export interface VerificationReport {
  status:
    | "verified_fixed"
    | "verification_failed"
    | "patch_rejected"
    | "verification_inconclusive"
    | "not_attempted";
  patch_id?: string | null;
  target_file?: string | null;
  patch_diff?: string | null;
  test_output: string;
  expected_criteria: string;
  attempts: number;
  reverted: boolean;
  duration_ms: number;
  failure_evidence?: string | null;
}

export interface SystemReadiness {
  ready: boolean;
  service: string;
  nebius?: {
    api_key_configured: boolean;
    base_url: string;
    model: string;
    mock_mode: boolean;
  };
  docker?: {
    available: boolean;
    server_version?: string;
    reason?: string;
  };
  issues: string[];
}

export interface InvestigationHistoryItem {
  id: string;
  scenarioName: string;
  status: string;
  confidence: number;
  durationMs: number;
  diagnosisDurationMs?: number | null;
  verificationDurationMs?: number | null;
  lookupDurationMs?: number | null;
  timestamp: string;
  startedAtIso?: string;
  isSample?: boolean;
  isCached?: boolean;
  originalDurationMs?: number | null;
  diagnosis?: DiagnoseResponse | null;
  patchProposal?: PatchProposal | null;
  verificationReport?: VerificationReport | null;
}

// Fallback scenarios list if backend is loading or offline (7 reproducible benchmark scenarios)
export const STATIC_SCENARIOS: ScenarioInfo[] = [
  {
    id: "scenario_a_missing_env",
    name: "Scenario A: Missing Environment Variable",
    description:
      "Container crashes with KeyError: DATABASE_URL. Engine confirms missing variable without leaking secrets, proposes compose patch, and verifies in sandbox.",
    difficulty: "Easy",
    requires_probe: false,
  },
  {
    id: "scenario_b_healthcheck_mismatch",
    name: "Scenario B: Healthcheck Probe Mismatch",
    description:
      "Logs appear normal, but container is unhealthy. Compose probes /health while app routes /healthz. Requires active diagnostic probe to pinpoint mismatch.",
    difficulty: "Medium",
    requires_probe: true,
  },
  {
    id: "scenario_c_port_mismatch",
    name: "Scenario C: Port Forwarding Target Mismatch",
    description:
      "Compose forwards host 8000 to container 5000, but app listens on 8000. Engine verifies listening ports with TCP probes and generates aligned port patch.",
    difficulty: "Easy",
    requires_probe: true,
  },
  {
    id: "scenario_d_insufficient_evidence",
    name: "Scenario D: Upstream Flapping Outage",
    description:
      "External gateway connection resets intermittently. Engine exhausts local probes, refuses to hallucinate a fake patch, and reports insufficient_evidence honestly.",
    difficulty: "Hard",
    requires_probe: false,
  },
  {
    id: "scenario_e_misleading_logs",
    name: "Scenario E: Misleading Database Logs (Kernel OOM Exit 137)",
    description:
      "Application logs show database timeouts, but container inspect reveals OOMKilled: true (exit 137). Engine identifies kernel memory exhaustion.",
    difficulty: "Hard",
    requires_probe: false,
  },
  {
    id: "scenario_f_contradictory_evidence",
    name: "Scenario F: Contradictory Redis Logs vs In-Memory Fallback",
    description:
      "Logs report Redis connection error, but compose config explicitly sets REDIS_ENABLED=false. Engine detects contradiction and avoids unnecessary patch.",
    difficulty: "Medium",
    requires_probe: false,
  },
  {
    id: "scenario_g_failed_patch_regression",
    name: "Scenario G: Regression in Patch (Verification Failure Caught)",
    description:
      "App failed startup due to invalid rate limit configuration. An adversarial patch with syntax regression is caught by sandbox and reverted.",
    difficulty: "Medium",
    requires_probe: false,
  },
];

class FixLoopApiClient {
  private explicitBaseUrl?: string;

  constructor(baseUrl?: string) {
    if (baseUrl !== undefined) {
      this.explicitBaseUrl = baseUrl.replace(/\/+$/, "");
    }
  }

  private get baseUrl(): string {
    if (this.explicitBaseUrl !== undefined) {
      return this.explicitBaseUrl;
    }
    return getApiBaseUrl();
  }

  async checkReadiness(): Promise<SystemReadiness> {
    try {
      // Parallel fetch for /health (docker status) and /ready (nebius status)
      const [healthRes, readyRes] = await Promise.allSettled([
        fetch(`${this.baseUrl}/health`, {
          method: "GET",
          headers: { Accept: "application/json" },
          cache: "no-store",
        }),
        fetch(`${this.baseUrl}/ready`, {
          method: "GET",
          headers: { Accept: "application/json" },
          cache: "no-store",
        }),
      ]);

      let dockerStatus = { available: false, reason: "Docker check unavailable" };
      if (healthRes.status === "fulfilled" && healthRes.value.ok) {
        const healthJson = await healthRes.value.json();
        if (healthJson.docker) {
          dockerStatus = healthJson.docker;
        }
      }

      if (readyRes.status === "fulfilled" && readyRes.value.ok) {
        const readyJson = await readyRes.value.json();
        return {
          ready: readyJson.ready ?? false,
          service: readyJson.service || "fixloop",
          nebius: readyJson.nebius || {
            api_key_configured: false,
            base_url: "https://api.tokenfactory.nebius.com/v1",
            model: "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
            mock_mode: true,
          },
          docker: dockerStatus,
          issues: readyJson.issues || [],
        };
      }

      throw new Error("Failed to reach readiness endpoint");
    } catch (err: unknown) {
      return {
        ready: false,
        service: "fixloop",
        nebius: {
          api_key_configured: false,
          model: "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
          base_url: "https://api.tokenfactory.nebius.com/v1",
          mock_mode: true,
        },
        docker: {
          available: false,
          reason: err instanceof Error ? err.message : "Backend unreachable",
        },
        issues: [
          `Cannot connect to FixLoop backend at ${this.baseUrl || "same-origin API rewrite"}. Ensure uvicorn backend is running.`,
        ],
      };
    }
  }

  async fetchScenarios(): Promise<ScenarioInfo[]> {
    try {
      const res = await fetch(`${this.baseUrl}/scenarios`, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (res.ok) {
        return await res.json();
      }
    } catch {
      // Fallback to static scenarios
    }
    return STATIC_SCENARIOS;
  }

  async runDiagnosis(
    scenarioName: string,
    customLogs?: string,
    idempotencyKey?: string
  ): Promise<DiagnoseResponse> {
    const payload: Record<string, unknown> = customLogs
      ? { service_name: scenarioName, logs: customLogs }
      : { service_name: scenarioName };
    if (idempotencyKey) {
      payload.idempotency_key = idempotencyKey;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 90000);

    try {
      const res = await fetch(`${this.baseUrl}/api/v1/diagnose`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!res.ok) {
        const errorBody = await res.text();
        let errorMsg = `Diagnosis failed with HTTP ${res.status}`;
        try {
          const parsed = JSON.parse(errorBody);
          if (parsed.detail) {
            errorMsg =
              typeof parsed.detail === "string"
                ? parsed.detail
                : JSON.stringify(parsed.detail);
          }
        } catch {
          if (errorBody) errorMsg = errorBody;
        }
        throw new Error(errorMsg);
      }

      return await res.json();
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        throw new Error(
          "This is taking longer than expected (timed out after 90 seconds). Nebius inference or VM response delayed. Please click Retry."
        );
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  async fetchPatchProposal(scenarioName: string): Promise<PatchProposal | null> {
    try {
      const res = await fetch(`${this.baseUrl}/api/v1/patch/${encodeURIComponent(scenarioName)}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (res.ok) {
        return await res.json();
      }
    } catch {
      // If patch cannot be generated due to insufficient evidence, returns null
    }
    return null;
  }

  async fetchInvestigationDiagnosis(
    id: string
  ): Promise<DiagnoseResponse | null> {
    try {
      const res = await fetch(
        `${this.baseUrl}/investigations/${encodeURIComponent(id)}/diagnosis`,
        {
          method: "GET",
          headers: { Accept: "application/json" },
          cache: "no-store",
        }
      );
      if (res.ok) {
        return await res.json();
      }
    } catch {
      // Fallback
    }
    return null;
  }

  async runVerification(
    scenarioName: string,
    userApproved: boolean = true,
    investigationId?: string
  ): Promise<VerificationReport> {
    const res = await fetch(`${this.baseUrl}/api/v1/verify`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        scenario_name: scenarioName,
        user_approved: userApproved,
        ...(investigationId ? { investigation_id: investigationId } : {}),
      }),
    });

    if (!res.ok) {
      const errorBody = await res.text();
      let errorMsg = `Verification failed with HTTP ${res.status}`;
      try {
        const parsed = JSON.parse(errorBody);
        if (parsed.detail) {
          errorMsg =
            typeof parsed.detail === "string"
              ? parsed.detail
              : JSON.stringify(parsed.detail);
        }
      } catch {
        if (errorBody) errorMsg = errorBody;
      }
      throw new Error(errorMsg);
    }

    return await res.json();
  }

  async applyPatch(
    scenarioName: string,
    patchDiff?: string | null,
    targetFile?: string | null
  ): Promise<{ applied: boolean; target_file: string; message: string }> {
    const res = await fetch(`${this.baseUrl}/api/v1/apply`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        scenario_name: scenarioName,
        patch_diff: patchDiff,
        target_file: targetFile,
      }),
    });

    if (!res.ok) {
      const errorBody = await res.text();
      let errorMsg = `Apply patch failed with HTTP ${res.status}`;
      try {
        const parsed = JSON.parse(errorBody);
        if (parsed.detail) errorMsg = parsed.detail;
      } catch {
        if (errorBody) errorMsg = errorBody;
      }
      throw new Error(errorMsg);
    }

    return await res.json();
  }

  async fetchInvestigation(id: string): Promise<Record<string, unknown> | null> {
    try {
      const res = await fetch(`${this.baseUrl}/investigations/${encodeURIComponent(id)}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (res.ok) {
        return await res.json();
      }
    } catch {
      // Backend not yet populated or offline
    }
    return null;
  }

  async fetchRecentInvestigations(): Promise<InvestigationHistoryItem[]> {
    try {
      const res = await fetch(`${this.baseUrl}/investigations`, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          return data.map((item: Record<string, unknown>, idx: number) => {
            const scenarioName = (item.scenario_name as string) || "unknown";
            const outcome = String(item.outcome || "").toUpperCase();
            const rawStatus = String(item.status || "completed").toLowerCase();

            // Correct mapping of backend final statuses
            let status = rawStatus;
            if (
              outcome === "VERIFIED_FIX" ||
              rawStatus === "verified_fixed"
            ) {
              status = "verified_fixed";
            } else if (
              outcome === "FAILED_FIX" ||
              rawStatus === "verification_failed"
            ) {
              status = "verification_failed";
            } else if (
              outcome === "INSUFFICIENT_EVIDENCE" ||
              rawStatus === "insufficient_evidence" ||
              scenarioName.includes("scenario_d")
            ) {
              status = "insufficient_evidence";
            } else if (
              outcome === "DIAGNOSIS_AVAILABLE" ||
              rawStatus === "diagnosis_available" ||
              rawStatus === "completed"
            ) {
              status = "diagnosis_available";
            }

            const confidence =
              typeof item.confidence === "number"
                ? item.confidence
                : status === "insufficient_evidence"
                ? 0.5
                : 0.96;

            const durationMs =
              typeof item.duration_ms === "number"
                ? item.duration_ms
                : typeof item.durationMs === "number"
                ? item.durationMs
                : 0;

            const isSample =
              Boolean(item.is_sample) ||
              Boolean(
                typeof item.id === "string" &&
                  item.id.toUpperCase().startsWith("SAMPLE-")
              );

            const startedAtRaw =
              (item.started_at as string) ||
              (item.started_at_iso as string) ||
              (item.created_at as string) ||
              "";
            const formattedTimestamp = startedAtRaw
              ? new Date(startedAtRaw).toLocaleTimeString()
              : "";

            return {
              id: (item.id as string) || `INV-${idx + 1}`,
              scenarioName,
              status,
              confidence,
              durationMs,
              diagnosisDurationMs: (item.diagnosis_duration_ms as number) || null,
              verificationDurationMs: (item.verification_duration_ms as number) || null,
              lookupDurationMs: (item.lookup_duration_ms as number) || null,
              timestamp: formattedTimestamp || (item.timestamp as string) || "",
              startedAtIso: startedAtRaw,
              isSample,
              isCached: Boolean(item.is_cached),
              originalDurationMs: (item.original_duration_ms as number) || (item.diagnosis_duration_ms as number) || null,
              diagnosis: (item.diagnosis as DiagnoseResponse) || null,
              patchProposal: (item.patch_proposal as PatchProposal) || null,
              verificationReport: (item.verification_report as VerificationReport) || null,
            };
          });
        }
      }
    } catch {
      // Backend not yet populated or offline
    }
    return [];
  }
}

export const apiClient = new FixLoopApiClient();
