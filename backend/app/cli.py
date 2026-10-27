"""FixLoop Instant CLI: Zero-Friction Autonomous SRE Diagnostics.

One-command diagnostic tool for:
1. Live local or remote Docker containers: `python -m backend.app.cli <container_name>`
2. Live remote web servers / URLs: `python -m backend.app.cli https://api.example.com/health`
3. Local application workspaces: `python -m backend.app.cli .`
"""

import sys
import subprocess
import json
import asyncio
import argparse
from pathlib import Path
import httpx

from backend.app.core.config import settings
from backend.app.core.models import DiagnoseRequest, DiagnosisStatus
from backend.app.llm.client import NebiusLLMClient
from backend.app.agent.engine import DiagnosticEngine


def get_docker_telemetry(container_name: str):
    """Pulls logs and inspect JSON directly from local or remote Docker daemon."""
    print(f"[*] Interrogating Docker daemon for container '{container_name}'...")
    try:
        logs_res = subprocess.run(
            ["docker", "logs", "--tail", "150", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        logs = (logs_res.stdout + "\n" + logs_res.stderr).strip()
    except Exception as e:
        logs = f"Error fetching logs: {e}"

    try:
        inspect_res = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if inspect_res.returncode == 0:
            parsed = json.loads(inspect_res.stdout)
            inspect_data = parsed[0] if parsed else {}
        else:
            inspect_data = {"error": inspect_res.stderr.strip()}
    except Exception as e:
        inspect_data = {"error": str(e)}

    return logs, inspect_data


async def probe_live_url(url: str):
    """Sends active probe to live server endpoint and captures telemetry."""
    print(f"[*] Probing live server endpoint: {url}...")
    headers = {"User-Agent": "FixLoop-SRE-LiveProbe/1.0"}
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            body = resp.text[:2000]
            summary = (
                f"HTTP Probe to {url} returned HTTP {resp.status_code} {resp.reason_phrase}.\n"
                f"Headers: {dict(resp.headers)}\n"
                f"Response Body:\n{body}"
            )
            return summary, {"status_code": resp.status_code, "url": url}
    except Exception as e:
        return f"HTTP Probe connection failed to {url}: {e}", {"error": str(e), "url": url}


async def run_cli():
    parser = argparse.ArgumentParser(
        description="FixLoop Instant Autonomous SRE CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python -m backend.app.cli my_container
  python -m backend.app.cli https://api.my-company.com/healthz
  python -m backend.app.cli ./scenarios/scenario_b_healthcheck_mismatch
        """,
    )
    parser.add_argument(
        "target",
        help="Docker container name, remote server URL (http/https), or directory path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Automatically apply verified patch to host disk if confidence >= 90%%",
    )
    args = parser.parse_args()

    target = args.target.strip()
    print("=" * 70)
    print("  FixLoop Autonomous SRE Engine - Powered by Nebius & NVIDIA Nemotron")
    print("=" * 70)

    # 1. Directory Target
    target_path = Path(target)
    if target_path.exists() and target_path.is_dir():
        print(f"[+] Diagnosing local project directory: {target_path.resolve()}")
        engine = DiagnosticEngine()
        result = await engine.run_investigation(project_root=target_path)
        print("\n" + "=" * 70)
        print(f"DIAGNOSIS: {result.status.value.upper()}")
        print(f"CONFIDENCE: {result.confidence * 100:.1f}%")
        print(f"SUMMARY: {result.summary}")
        print("=" * 70)
        for idx, h in enumerate(result.hypotheses, 1):
            print(f"\n[{idx}] {h.description} (Confidence: {h.confidence * 100:.0f}%)")
            for sup in h.supporting_evidence:
                print(f"    + Evidence: {sup}")
        print("\n" + "=" * 70)
        print(f"NEXT ACTION: {result.next_action}")
        return

    # 2. Remote URL Target
    if target.startswith("http://") or target.startswith("https://"):
        logs, inspect_data = await probe_live_url(target)
        service_name = target.split("//")[-1].split("/")[0]
    # 3. Docker Container Target
    else:
        service_name = target
        logs, inspect_data = get_docker_telemetry(target)

    client = NebiusLLMClient()
    req = DiagnoseRequest(
        service_name=service_name,
        logs=logs,
        docker_inspect=inspect_data if isinstance(inspect_data, dict) and "error" not in inspect_data else None,
    )

    print(f"[*] Ingesting live telemetry ({len(logs)} chars). Calling NVIDIA Nemotron via Nebius...")
    res = await client.diagnose(req)

    print("\n" + "=" * 70)
    print(f"OUTCOME:    {res.status.value.upper()}")
    print(f"CONFIDENCE: {res.confidence * 100:.1f}%")
    print(f"SUMMARY:    {res.summary}")
    print("=" * 70)

    if res.hypotheses:
        print("\nRanked Root-Cause Hypotheses:")
        for idx, h in enumerate(res.hypotheses, 1):
            print(f"  [{idx}] {h.description} ({h.confidence * 100:.0f}% confidence)")
            if h.recommended_discriminating_test:
                print(f"      -> Recommended Test: {h.recommended_discriminating_test}")

    if res.contradictions:
        print("\nContradictions Detected Across Evidence:")
        for c in res.contradictions:
            print(f"  [!] {c.description} (Severity: {c.severity})")

    print("\n" + "=" * 70)
    print(f"RECOMMENDED NEXT ACTION: {res.next_action}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_cli())
