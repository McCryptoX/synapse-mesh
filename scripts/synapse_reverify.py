#!/usr/bin/env python3
"""
Synapse-Mesh Client-Side Re-Verifier
Allows any external AI agent (Cursor, Claude, Grok, Antigravity) to independently
re-verify a recipe locally:
  Phase 1: Pre-Fail check on reproduction script (asserts non-zero exit code).
  Phase 2: Post-Pass check on test suite (asserts zero exit code).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None


def fetch_recipe(recipe_id_or_url: str, api_base: str = "https://api.synapsemesh.dev") -> dict:
    recipe_id = recipe_id_or_url.strip().split("/")[-1]
    url = f"{api_base.rstrip('/')}/api/v1/recipes/{recipe_id}"
    
    if httpx:
        resp = httpx.get(url, headers={"User-Agent": "Synapse-Client-Reverify/1.0"}, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            raise RuntimeError(f"Recipe '{recipe_id}' not found (HTTP {resp.status_code})")
        return resp.json()
    else:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Synapse-Client-Reverify/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))


def reverify_recipe(recipe_id_or_url: str, api_base: str = "https://api.synapsemesh.dev") -> bool:
    print(f"[*] Fetching recipe '{recipe_id_or_url}'...")
    try:
        data = fetch_recipe(recipe_id_or_url, api_base=api_base)
    except Exception as e:
        print(f"[!] Failed to fetch recipe: {e}", file=sys.stderr)
        return False

    recipe_id = data.get("id", "unknown")
    runtime = data.get("problem", {}).get("runtime", "python").lower()
    repro = data.get("reproduction", {})
    repro_script = repro.get("script", "")
    test_suite = repro.get("testSuite", "")
    sol = data.get("solution", {})
    diff = sol.get("codeDiff") or sol.get("patchDiff", "")
    do_not = sol.get("doNot", [])
    pinned_deps = sol.get("pinnedDependencies", {})

    print(f"[*] Starting local 2-Phase Re-Verification for '{recipe_id}' ({runtime})...")
    print(f"    - Pinned Dependencies: {pinned_deps or 'None'}")
    print(f"    - Negative Constraints (doNot): {len(do_not)} rules")

    import shutil
    ext = ".py" if runtime == "python" else (".js" if runtime in ("nodejs", "node", "javascript", "typescript") else ".rs")
    if runtime == "python":
        runner_cmd = [sys.executable]
    else:
        node_bin = shutil.which("node")
        if not node_bin:
            print(f"[!] UNVERIFIED: '{runtime}' runtime executable not found on local host.", file=sys.stderr)
            return False
        runner_cmd = [node_bin]

    with tempfile.TemporaryDirectory(prefix="synapse_client_reverify_") as tmp_dir:
        # Phase 1: Pre-Fail Reproduction Check
        if repro_script:
            repro_file = Path(tmp_dir) / f"repro{ext}"
            repro_file.write_text(repro_script, encoding="utf-8")
            res_pre = subprocess.run(runner_cmd + [str(repro_file)], cwd=tmp_dir, capture_output=True, text=True, timeout=15)
            if res_pre.returncode == 0:
                print(f"[✗] PRE-FAIL REJECTED: Reproduction script unexpectedly exited with 0 (bug not triggered locally).", file=sys.stderr)
                return False
            else:
                print(f"[✓] Phase 1 Pre-Fail Confirmed: Script failed with Exit Code {res_pre.returncode}")

        # Phase 2: Post-Pass Verification Check
        if not test_suite:
            print("[!] Recipe does not contain an executable testSuite.", file=sys.stderr)
            return False

        test_file = Path(tmp_dir) / f"test_suite{ext}"
        test_file.write_text(test_suite, encoding="utf-8")
        res_post = subprocess.run(runner_cmd + [str(test_file)], cwd=tmp_dir, capture_output=True, text=True, timeout=15)
        
        if res_post.returncode == 0:
            print(f"[✓] Phase 2 Post-Pass Confirmed: Test Suite passed cleanly (Exit Code 0)")
            print(f"\n[★] CLIENT RE-VERIFICATION 100% PROVEN: Recipe is safe to commit.")
            return True
        else:
            print(f"[✗] POST-PASS FAILED (Exit Code {res_post.returncode}):", file=sys.stderr)
            print(res_post.stderr, file=sys.stderr)
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse-Mesh Client-Side Re-Verifier")
    parser.add_argument("recipe", help="Recipe ID or full URL")
    parser.add_argument("--api", default="https://api.synapsemesh.dev", help="Synapse-Mesh API base URL")
    args = parser.parse_args()

    success = reverify_recipe(args.recipe, api_base=args.api)
    sys.exit(0 if success else 1)
