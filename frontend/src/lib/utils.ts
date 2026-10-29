import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function getStatusColor(status: string): {
  bg: string;
  text: string;
  border: string;
  badge: string;
  dot: string;
} {
  switch (status?.toLowerCase()) {
    case "verified_fixed":
      return {
        bg: "bg-emerald-950/40",
        text: "text-emerald-400",
        border: "border-emerald-800/60",
        badge: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
        dot: "bg-emerald-500",
      };
    case "verification_failed":
    case "failure":
    case "failed":
      return {
        bg: "bg-rose-950/40",
        text: "text-rose-400",
        border: "border-rose-800/60",
        badge: "bg-rose-500/15 text-rose-400 border-rose-500/30",
        dot: "bg-rose-500",
      };
    case "patch_rejected":
      return {
        bg: "bg-amber-950/40",
        text: "text-amber-400",
        border: "border-amber-800/60",
        badge: "bg-amber-500/15 text-amber-400 border-amber-500/30",
        dot: "bg-amber-500",
      };
    case "diagnosis_available":
      return {
        bg: "bg-cyan-950/40",
        text: "text-cyan-400",
        border: "border-cyan-800/60",
        badge: "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
        dot: "bg-cyan-500",
      };
    case "insufficient_evidence":
    case "not_attempted":
      return {
        bg: "bg-purple-950/40",
        text: "text-purple-400",
        border: "border-purple-800/60",
        badge: "bg-purple-500/15 text-purple-400 border-purple-500/30",
        dot: "bg-purple-500",
      };
    case "investigating":
    case "running":
      return {
        bg: "bg-blue-950/40",
        text: "text-blue-400",
        border: "border-blue-800/60",
        badge: "bg-blue-500/15 text-blue-400 border-blue-500/30",
        dot: "bg-blue-500 animate-ping",
      };
    default:
      return {
        bg: "bg-slate-900/60",
        text: "text-slate-400",
        border: "border-slate-800",
        badge: "bg-slate-800 text-slate-300 border-slate-700",
        dot: "bg-slate-500",
      };
  }
}

export function extractEnvVarInfo(text: string): { varName: string; defaultVal: string } | null {
  if (!text) return null;
  // 1. Regex for KeyError: 'VAR' or KeyError 'VAR'
  const keyErrorMatch = text.match(/keyerror[:\s]+['"]([A-Z0-9_]+)['"]/i);
  let varName: string | null = keyErrorMatch ? keyErrorMatch[1].toUpperCase() : null;

  if (!varName) {
    // 2. Regex for missing environment variable VAR
    const missingMatch = text.match(
      /(?:missing|unset|undefined)(?:\s+required)?(?:\s+environment)?\s+variable[:\s]+['"]?([A-Z0-9_]{2,})['"]?/i
    );
    if (missingMatch) {
      varName = missingMatch[1].toUpperCase();
    }
  }

  if (!varName) {
    // 3. Known variable patterns
    const knownVars = [
      "REDIS_URL", "DATABASE_URL", "SECRET_KEY", "JWT_SECRET", "API_KEY",
      "RABBITMQ_URL", "MONGO_URI", "MONGODB_URI", "POSTGRES_URL",
      "BACKEND_URL", "AUTH_TOKEN", "SESSION_SECRET"
    ];
    for (const known of knownVars) {
      const rx = new RegExp(`\\b${known}\\b`, "i");
      if (rx.test(text)) {
        varName = known;
        break;
      }
    }
  }

  if (!varName) return null;

  const vUpper = varName.toUpperCase();
  let defaultVal = `http://localhost:8000/${vUpper.toLowerCase()}`;
  if (vUpper.includes("REDIS")) {
    defaultVal = "redis://localhost:6379/0";
  } else if (vUpper.includes("DATABASE") || vUpper.includes("POSTGRES")) {
    defaultVal = "postgresql://app_user:app_pass@localhost:5432/app_db";
  } else if (vUpper.includes("MONGO")) {
    defaultVal = "mongodb://localhost:27017/app_db";
  } else if (vUpper.includes("RABBIT") || vUpper.includes("AMQP")) {
    defaultVal = "amqp://guest:guest@localhost:5672/";
  } else if (vUpper.includes("PORT")) {
    defaultVal = "8080";
  } else if (["SECRET", "KEY", "TOKEN"].some((k) => vUpper.includes(k))) {
    defaultVal = "dev_secret_key_change_in_production";
  }

  return { varName: vUpper, defaultVal };
}

