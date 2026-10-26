/**
 * FixLoop API Client & TypeScript Interfaces
 * Connects directly to FastAPI backend endpoints with graceful offline/loading fallbacks.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export interface ScenarioInfo {
  id: string;
  name: string;
  description: string;
  difficulty: "Easy" | "Medium" | "Hard";
  requires_probe: boolean;
}

export interface DiagnoseHypothesis {
  id: string;
  description: string;
  confidence: number;
  supporting_evidence: string[];
  refuting_evidence: string[];
}

export interface EvidenceRecord {
  source: string;
  type: string;
  confidence: number;
  summary: string;
  details?: Record<string, unknown> | string;
  timestamp: string;
}

export interface RecommendedTest {
  test_name: string;
  expected_gain: string;
  rationale: string;
  safety_level: "READ_ONLY" | "LOW_RISK" | "HIGH_RISK";
}

export interface AuditLog {
  observations: string[];
  probes_executed: string[];
  stop_reason: string;
}

export interface DiagnoseResponse {
  status: "diagnosis_available" | "insufficient_evidence" | "needs_more_probes";
  summary: string;
  hypotheses: DiagnoseHypothesis[];
  evidence: EvidenceRecord[];
  recommended_tests: RecommendedTest[];
  missing_information: string[];
  confidence: number;
  next_action: string;
  audit_log?: AuditLog;
}

export interface VerificationReport {
  status:
    | "verified_fixed"
    | "verification_failed"
    | "patch_rejected"
    | "verification_inconclusive"
    | "not_attempted";
  patch_id?: string;
  target_file?: string;
  patch_diff?: string;
  test_output: string;
  expected_criteria: string;
  attempts: number;
  reverted: boolean;
  duration_ms: number;
  failure_evidence?: string;
}

export interface SystemReadiness {
  ready: boolean;
  nebius_api_key_configured: boolean;
  model_name: string;
  base_url: string;
  docker_daemon: {
    available: boolean;
    server_version?: string;
    reason?: string;
  };
  issues?: string[];
}

// Fallback scenarios list if backend is loading
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
];

class FixLoopApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  async checkReadiness(): Promise<SystemReadiness> {
    try {
      const res = await fetch(`${this.baseUrl}/ready`, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      return await res.json();
    } catch (err: unknown) {
      return {
        ready: false,
        nebius_api_key_configured: false,
        model_name: "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        base_url: "https://api.tokenfactory.nebius.com/v1",
        docker_daemon: {
          available: false,
          reason: err instanceof Error ? err.message : "Backend unreachable",
        },
        issues: [
          `Cannot connect to FixLoop backend at ${this.baseUrl}. Ensure uvicorn backend is running.`,
        ],
      };
    }
  }

  async fetchScenarios(): Promise<ScenarioInfo[]> {
    try {
      const res = await fetch(`${this.baseUrl}/scenarios`, {
        method: "GET",
        headers: { Accept: "application/json" },
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
    customLogs?: string
  ): Promise<DiagnoseResponse> {
    const payload = customLogs
      ? { service_name: scenarioName, logs: customLogs }
      : { service_name: scenarioName };

    const res = await fetch(`${this.baseUrl}/api/v1/diagnose`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errorBody = await res.text();
      let errorMsg = `Diagnosis failed with HTTP ${res.status}`;
      try {
        const parsed = JSON.parse(errorBody);
        if (parsed.detail) {
          errorMsg = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
        }
      } catch {
        // use raw errorBody
        if (errorBody) errorMsg = errorBody;
      }
      throw new Error(errorMsg);
    }

    return await res.json();
  }

  async runVerification(
    scenarioName: string,
    userApproved: boolean = true
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
      }),
    });

    if (!res.ok) {
      const errorBody = await res.text();
      let errorMsg = `Verification failed with HTTP ${res.status}`;
      try {
        const parsed = JSON.parse(errorBody);
        if (parsed.detail) {
          errorMsg = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
        }
      } catch {
        if (errorBody) errorMsg = errorBody;
      }
      throw new Error(errorMsg);
    }

    return await res.json();
  }
}

export const apiClient = new FixLoopApiClient();
