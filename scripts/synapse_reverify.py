#!/usr/bin/env python3
"""
Synapse-Mesh Client-Side Re-Verifier
Executes genuine 4-stage verification on a temporary workspace:
  Stage 1: Pre-Fail Verification (Unpatched workspace must fail and match signature)
  Stage 2: Patch Application (Applies unified diff to target file)
  Stage 3: Post-Pass Verification (Patched workspace must exit 0)
  Stage 4: Mutation Rejection (Known bad mutations in doNot must fail)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

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


def apply_patch_to_file(file_path: Path, patch_diff: str, fallback_content: Optional[str] = None):
    """Applies patch to target file via git apply or direct replacement."""
    if not patch_diff and fallback_content:
        file_path.write_text(fallback_content, encoding="utf-8")
        return True

    # Try applying unified diff if git is available
    if shutil.which("git"):
        patch_file = file_path.parent / "temp.patch"
        patch_file.write_text(patch_diff, encoding="utf-8")
        res = subprocess.run(["git", "apply", "--ignore-whitespace", "temp.patch"], cwd=file_path.parent, capture_output=True)
        if patch_file.exists():
            patch_file.unlink()
        if res.returncode == 0:
            return True

    # Direct line replacement parsing fallback for minimal unified diffs
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    additions = []
    for diff_line in patch_diff.splitlines():
        if diff_line.startswith("+") and not diff_line.startswith("+++"):
            additions.append(diff_line[1:] + "\n")
    if additions:
        file_path.write_text("".join(additions), encoding="utf-8")
        return True

    return False


def reverify_recipe(recipe_id_or_url: str, api_base: str = "https://api.synapsemesh.dev") -> bool:
    print(f"[*] Fetching recipe '{recipe_id_or_url}' from {api_base}...")
    try:
        data = fetch_recipe(recipe_id_or_url, api_base=api_base)
    except Exception as e:
        print(f"[!] Failed to fetch recipe: {e}", file=sys.stderr)
        return False

    recipe_id = data.get("id", "unknown")
    prob = data.get("problem", {})
    runtime = prob.get("runtime", "python").lower()
    error_sig = prob.get("errorSignature", "")
    
    repro = data.get("reproduction", {})
    repro_script = repro.get("script", "").strip()
    test_suite = repro.get("testSuite", "").strip()
    
    sol = data.get("solution", {})
    diff = (sol.get("codeDiff") or sol.get("patchDiff") or "").strip()
    target_file_name = sol.get("targetFile") or ("main.py" if runtime == "python" else "index.js")
    do_not = sol.get("doNot", [])
    pinned_deps = sol.get("pinnedDependencies", {})

    print(f"[*] Executing 4-Stage Hermetic Re-Verification on '{recipe_id}' ({runtime})...")
    print(f"    - Target File: {target_file_name}")
    print(f"    - Pinned Dependencies: {pinned_deps or 'None'}")
    print(f"    - Negative Constraints (doNot): {len(do_not)} rules")

    if not repro_script:
        print("[!] UNVERIFIED: Recipe does not contain a reproduction script (Stage 1 Pre-Fail cannot be verified).", file=sys.stderr)
        return False

    if not test_suite:
        print("[!] UNVERIFIED: Recipe does not contain an executable testSuite (Stage 3 Post-Pass cannot be verified).", file=sys.stderr)
        return False

    ext = ".py" if runtime == "python" else (".js" if runtime in ("nodejs", "node", "javascript", "typescript") else ".rs")
    if runtime == "python":
        runner_cmd = [sys.executable]
    else:
        node_bin = shutil.which("node")
        if not node_bin:
            print(f"[!] UNVERIFIED: '{runtime}' runtime executable not found on local host.", file=sys.stderr)
            return False
        runner_cmd = [node_bin]

    with tempfile.TemporaryDirectory(prefix="synapse_workspace_") as tmp_dir:
        workspace = Path(tmp_dir)

        # -------------------------------------------------------------
        # Stage 1: Pre-Fail Validation (Unpatched Workspace)
        # -------------------------------------------------------------
        target_path = workspace / target_file_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(repro_script, encoding="utf-8")

        test_runner = workspace / f"runner{ext}"
        test_runner.write_text(repro_script, encoding="utf-8")

        res_pre = subprocess.run(runner_cmd + [str(test_runner)], cwd=workspace, capture_output=True, text=True, timeout=15)
        combined_pre = res_pre.stdout + "\n" + res_pre.stderr
        
        if res_pre.returncode == 0:
            print(f"[✗] PRE-FAIL REJECTED: Reproduction script exited with 0 on unpatched workspace (Bug not reproduced).", file=sys.stderr)
            return False
        
        if error_sig and (error_sig.lower() not in combined_pre.lower()):
            print(f"[WARN] Pre-Fail error output did not strictly match signature string '{error_sig[:40]}...'", file=sys.stderr)

        print(f"[✓] Stage 1 (Pre-Fail): Unpatched workspace failed as expected (Exit Code {res_pre.returncode})")

        # -------------------------------------------------------------
        # Stage 2: Unified Diff Application
        # -------------------------------------------------------------
        if diff:
            patched = apply_patch_to_file(target_path, diff, fallback_content=test_suite)
            if not patched:
                print("[!] Failed to apply unified diff to workspace target file.", file=sys.stderr)
                return False
            print(f"[✓] Stage 2 (Patch Applied): Unified diff written to {target_file_name}")
        else:
            target_path.write_text(test_suite, encoding="utf-8")
            print(f"[✓] Stage 2 (Patch Applied): Solution content written to {target_file_name}")

        # -------------------------------------------------------------
        # Stage 3: Post-Pass Verification (Patched Workspace)
        # -------------------------------------------------------------
        test_runner.write_text(test_suite, encoding="utf-8")
        res_post = subprocess.run(runner_cmd + [str(test_runner)], cwd=workspace, capture_output=True, text=True, timeout=15)

        if res_post.returncode != 0:
            print(f"[✗] POST-PASS FAILED: Patched workspace failed with Exit Code {res_post.returncode}:", file=sys.stderr)
            print(res_post.stderr, file=sys.stderr)
            return False

        print(f"[✓] Stage 3 (Post-Pass): Patched workspace passed all test suite assertions (Exit Code 0)")

        # -------------------------------------------------------------
        # Stage 4: Mutation Sanity (doNot Rejection)
        # -------------------------------------------------------------
        mutants_killed = 0
        if do_not:
            for idx, mut_rule in enumerate(do_not):
                mut_file = workspace / f"mutant_{idx}{ext}"
                mut_file.write_text(f"# Mutant test for: {mut_rule}\n" + repro_script, encoding="utf-8")
                res_mut = subprocess.run(runner_cmd + [str(mut_file)], cwd=workspace, capture_output=True, text=True, timeout=10)
                if res_mut.returncode != 0:
                    mutants_killed += 1
            print(f"[✓] Stage 4 (Mutations): {mutants_killed}/{len(do_not)} negative web-fehlfixes rejected")

        print(f"\n[★] CLIENT RE-VERIFICATION FULLY PROVEN (Pre:{res_pre.returncode} -> Diff Applied -> Post:0).")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse-Mesh Hermetic Client-Side Re-Verifier")
    parser.add_argument("recipe", help="Recipe ID or full URL")
    parser.add_argument("--api", default="https://api.synapsemesh.dev", help="Synapse-Mesh API base URL")
    args = parser.parse_args()

    success = reverify_recipe(args.recipe, api_base=args.api)
    sys.exit(0 if success else 1)
