"""
Synapse-Mesh Universal CLI
Commands:
  - synapse search <query>: Queries verified compatibility bundles via MCP/REST.
  - synapse reverify <bundle_id>: Runs local 2-phase sandbox verification (Pre-Fail + Post-Pass).
  - synapse doctor: Checks local compiler toolchains & Synapse-Mesh node connectivity.
  - synapse install-mcp: Automatically registers Synapse MCP server in Cursor, Claude, Antigravity.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    httpx = None

API_DEFAULT = "https://api.synapsemesh.dev"


def cmd_doctor(api_base: str):
    """Diagnoses local environment toolchains and network connectivity."""
    print("================================================================================")
    print(" SYNAPSE-MESH AGENT ENVIRONMENT DOCTOR")
    print("================================================================================")
    print(f"Platform: {platform.platform()}")
    print(f"Python:   {platform.python_version()} ({sys.executable})")

    # Check Node.js
    node_v = shutil.which("node")
    if node_v:
        try:
            ver = subprocess.check_output([node_v, "--version"], text=True).strip()
            print(f"Node.js:  {ver} ({node_v}) [OK]")
        except Exception:
            print(f"Node.js:  Found at {node_v} but execution failed [WARN]")
    else:
        print("Node.js:  Not found on PATH [WARN - Node recipes require Node.js]")

    # Check Rust / Cargo
    rustc_v = shutil.which("rustc")
    cargo_v = shutil.which("cargo")
    if rustc_v and cargo_v:
        try:
            ver = subprocess.check_output([rustc_v, "--version"], text=True).strip()
            print(f"Rust:     {ver} [OK]")
        except Exception:
            print("Rust:     Found but failed to query version [WARN]")
    else:
        print("Rust:     Toolchain not found [INFO - Rust recipes require rustc/cargo]")

    # Check API Connectivity
    print("-" * 80)
    print(f"Connecting to Synapse-Mesh Node ({api_base})... ", end="", flush=True)
    try:
        if httpx:
            r = httpx.get(f"{api_base}/health", timeout=5.0)
            status = r.json().get("status", "unknown") if r.status_code == 200 else f"HTTP {r.status_code}"
        else:
            import urllib.request
            req = urllib.request.Request(f"{api_base}/health")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                status = json.loads(resp.read().decode()).get("status", "unknown")
        print(f"[ONLINE: {status}]")
    except Exception as e:
        print(f"[OFFLINE / ERROR: {e}]")
    print("================================================================================")


def cmd_search(query: str, runtime: Optional[str], api_base: str):
    """Queries verified compatibility bundles with token-dense output."""
    url = f"{api_base.rstrip('/')}/api/v1/recipes/search"
    payload = {"errorSignature": query, "limit": 5}
    if runtime:
        payload["runtime"] = runtime

    print(f"[*] Searching Synapse-Mesh for: '{query}'...")
    try:
        if httpx:
            r = httpx.post(url, json=payload, timeout=8.0)
            data = r.json()
        else:
            import urllib.request
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[!] Query failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not data:
        print("[!] No verified compatibility bundles found matching query.")
        sys.exit(0)

    print(f"\n[✓] Found {len(data)} Verified Compatibility Bundle(s):\n" + "="*80)
    for b in data:
        bid = b.get("id")
        prob = b.get("problem", {})
        sol = b.get("solution", {})
        evi = b.get("evidence", {})
        diff = sol.get("codeDiff") or sol.get("patchDiff") or ""
        pins = sol.get("pinnedDependencies") or prob.get("packages") or {}
        do_not = sol.get("doNot", [])

        print(f"BUNDLE ID: {bid}")
        print(f"RUNTIME:   {prob.get('runtime')} | STATUS: {evi.get('verificationStatus')} (Kills: {evi.get('mutationsKilled', 'N/A')})")
        print(f"ERROR:     {prob.get('errorSignature')}")
        if pins:
            print(f"PINS:      {pins}")
        print(f"SUMMARY:   {sol.get('summary')}")
        if do_not:
            print(f"DO NOT:    {do_not}")
        if diff:
            print(f"\n--- UNIFIED DIFF ---\n{diff.strip()}\n--------------------")
        print(f"VERIFY:    synapse reverify {bid}")
        print("="*80)


def cmd_reverify(bundle_id: str, api_base: str):
    """Executes 2-phase client-side verification on local machine."""
    from scripts.synapse_reverify import reverify_recipe
    ok = reverify_recipe(bundle_id, api_base=api_base)
    sys.exit(0 if ok else 1)


def cmd_install_mcp():
    """Injects Synapse-Mesh MCP server config into Cursor, Claude Desktop, Antigravity."""
    configs_written = 0
    
    def inject(file_path: Path, app_name: str):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        if "mcpServers" not in data:
            data["mcpServers"] = {}
        data["mcpServers"]["synapse-mesh"] = {
            "url": "https://mcp.synapsemesh.dev/mcp",
            "type": "streamable-http"
        }
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[✓] Registered Synapse-Mesh MCP in {app_name}: {file_path}")
        nonlocal configs_written
        configs_written += 1

    home = Path.home()
    # Claude Desktop macOS (only if application directory exists)
    claude_mac = home / "Library/Application Support/Claude/claude_desktop_config.json"
    if claude_mac.parent.exists():
        inject(claude_mac, "Claude Desktop (macOS)")

    # Claude Desktop Linux (only if application directory exists)
    claude_linux = home / ".config/Claude/claude_desktop_config.json"
    if claude_linux.parent.exists():
        inject(claude_linux, "Claude Desktop (Linux)")

    # Cursor
    cursor_cfg = home / ".cursor/mcp.json"
    if (home / ".cursor").exists():
        inject(cursor_cfg, "Cursor Editor")

    # Antigravity CLI
    agy_cfg = home / ".gemini/antigravity-cli/mcp_config.json"
    if agy_cfg.parent.exists():
        inject(agy_cfg, "Google Antigravity CLI")

    if configs_written == 0:
        fallback = home / ".synapse-mesh/mcp.json"
        inject(fallback, "Generic MCP Client")

    print(f"\n[★] Synapse-Mesh MCP installed successfully in {configs_written} client configuration(s)!")
    print("Endpoint: https://mcp.synapsemesh.dev/mcp (Protocol Spec 2026-07-28)")


def cli_entrypoint():
    parser = argparse.ArgumentParser(
        prog="synapse",
        description="Synapse-Mesh CLI: The Open Verified Compatibility Layer for Software Agents"
    )
    parser.add_argument("--api", default=API_DEFAULT, help="Synapse-Mesh API base URL")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Search
    p_search = subparsers.add_parser("search", help="Search verified compatibility bundles")
    p_search.add_argument("query", help="Error message, exception, or traceback snippet")
    p_search.add_argument("--runtime", help="Filter by runtime (e.g. python, nodejs, rust)")

    # Reverify
    p_reverify = subparsers.add_parser("reverify", help="Locally re-verify a bundle in isolated sandbox")
    p_reverify.add_argument("bundle", help="Bundle ID (e.g. rec_svelte5_runes_migration_065) or URL")

    # Doctor
    subparsers.add_parser("doctor", help="Check local toolchains and node connectivity")

    # Install MCP
    subparsers.add_parser("install-mcp", help="Auto-register Synapse MCP in Cursor, Claude, Antigravity")

    args = parser.parse_args()

    if args.command == "doctor":
        cmd_doctor(args.api)
    elif args.command == "search":
        cmd_search(args.query, args.runtime, args.api)
    elif args.command == "reverify":
        cmd_reverify(args.bundle, args.api)
    elif args.command == "install-mcp":
        cmd_install_mcp()
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_entrypoint()
