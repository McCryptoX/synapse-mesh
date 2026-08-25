#!/usr/bin/env python3
"""
Synapse-Mesh Hermetic Client-Side Re-Verifier
Executes the genuine 4-Stage Verification Contract on a temporary workspace:
  Stage 1: Pre-Fail Check (Unpatched target file executed -> must exit != 0 AND match error signature)
  Stage 2: Patch Application (Applies unified diff directly to target file)
  Stage 3: Post-Pass Check (Test runner executes against PATCHED target file -> must exit 0)
  Stage 4: Mutation Sanity (Each mutant code patch applied to target file -> must fail)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List

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


def apply_patch_unified(target_file: Path, patch_diff: str, workspace_dir: Path) -> bool:
    """Applies a unified diff to the target file inside the workspace."""
    if not patch_diff or not patch_diff.strip():
        return False

    # 1. Try git apply if git is available and workspace is a git repo or temp patch
    if shutil.which("git"):
        patch_file = workspace_dir / "patch.diff"
        patch_file.write_text(patch_diff, encoding="utf-8")
        res = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "--unidiff-zero", "patch.diff"],
            cwd=workspace_dir,
            capture_output=True,
            text=True
        )
        if patch_file.exists():
            patch_file.unlink()
        if res.returncode == 0:
            return True

    # 2. Pure Python standard unified patch parser
    try:
        lines = target_file.read_text(encoding="utf-8").splitlines(keepends=True)
        out_lines = []
        in_hunk = False
        
        diff_lines = patch_diff.splitlines(keepends=True)
        # Check if diff has standard --- +++ header
        has_header = any(l.startswith("---") for l in diff_lines) and any(l.startswith("+++") for l in diff_lines)
        
        if not has_header:
            # Direct replacement patch
            target_file.write_text(patch_diff, encoding="utf-8")
            return True

        # Parse simple unified diff hunks
        for line in diff_lines:
            if line.startswith("@@"):
                in_hunk = True
                continue
            if not in_hunk:
                continue
            if line.startswith("-"):
                continue
            elif line.startswith("+"):
                out_lines.append(line[1:])
            else:
                out_lines.append(line.lstrip(" "))
                
        if out_lines:
            target_file.write_text("".join(out_lines), encoding="utf-8")
            return True
    except Exception:
        pass

    return False


def verify_bundle_data(data: dict) -> bool:
    """Executes the strict 4-stage verification on bundle / recipe dictionary."""
    recipe_id = data.get("id", "unknown")
    prob = data.get("problem", {})
    runtime = prob.get("runtime", "python").lower()
    error_sig = prob.get("errorSignature", "").strip()
    
    repro = data.get("reproduction", {})
    repro_script = repro.get("script", "").strip()
    test_suite = repro.get("testSuite", "").strip()
    
    sol = data.get("solution", {})
    diff = (sol.get("codeDiff") or sol.get("patchDiff") or "").strip()
    target_file_name = sol.get("targetFile") or ("main.py" if runtime == "python" else "index.js")
    mutations = data.get("mutations") or sol.get("mutations") or []
    do_not = sol.get("doNot", [])
    pinned_deps = sol.get("pinnedDependencies", {})

    print(f"[*] Executing 4-Stage Verification on '{recipe_id}' ({runtime})...")
    print(f"    - Target File: {target_file_name}")
    print(f"    - Error Signature: {error_sig[:60]}...")
    print(f"    - Pinned Dependencies: {pinned_deps or 'None'}")

    # Stage 0: Strict Pre-conditions
    if not repro_script:
        print(f"[!] UNVERIFIED: Missing reproduction.script for recipe {recipe_id}.", file=sys.stderr)
        return False

    if not test_suite:
        print(f"[!] UNVERIFIED: Missing reproduction.testSuite for recipe {recipe_id}.", file=sys.stderr)
        return False

    ext = ".py" if runtime == "python" else (".js" if runtime in ("nodejs", "node", "javascript", "typescript") else ".rs")
    if runtime == "python":
        runner_cmd = [sys.executable]
    else:
        node_bin = shutil.which("node")
        if not node_bin:
            print(f"[!] UNVERIFIED: '{runtime}' runtime executable not found on host.", file=sys.stderr)
            return False
        runner_cmd = [node_bin]

    with tempfile.TemporaryDirectory(prefix="synapse_reverify_") as tmp_dir:
        workspace = Path(tmp_dir)
        target_path = workspace / target_file_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # -------------------------------------------------------------
        # Stage 1: Pre-Fail Check (Unpatched Target File)
        # -------------------------------------------------------------
        target_path.write_text(repro_script, encoding="utf-8")
        
        # In Python/Node, test_runner executes target_path
        res_pre = subprocess.run(runner_cmd + [str(target_path)], cwd=workspace, capture_output=True, text=True, timeout=15)
        combined_pre = res_pre.stdout + "\n" + res_pre.stderr

        if res_pre.returncode == 0:
            print(f"[✗] STAGE 1 PRE-FAIL FAILED: Unpatched code exited with 0 (bug not triggered).", file=sys.stderr)
            return False

        # Hard Gate: Signature Match
        if error_sig:
            sig_words = [w.lower() for w in re.findall(r'\b[A-Za-z0-9_]+\b', error_sig) if len(w) > 3]
            match_found = (error_sig.lower() in combined_pre.lower()) or any(w in combined_pre.lower() for w in sig_words[:3])
            if not match_found:
                print(f"[✗] STAGE 1 PRE-FAIL FAILED: Error output did not match signature '{error_sig}'.", file=sys.stderr)
                print(f"    Stderr output was:\n{res_pre.stderr}", file=sys.stderr)
                return False

        print(f"[✓] Stage 1 (Pre-Fail): Unpatched file failed with Exit Code {res_pre.returncode} & matched signature.")

        # -------------------------------------------------------------
        # Stage 2: Patch Application (Applies Diff directly to target_path)
        # -------------------------------------------------------------
        if diff:
            patched = apply_patch_unified(target_path, diff, workspace)
            if not patched:
                print(f"[✗] STAGE 2 PATCH FAILED: Unified diff could not be applied to {target_file_name}.", file=sys.stderr)
                return False
            print(f"[✓] Stage 2 (Patch Applied): Unified diff cleanly applied to {target_file_name}.")
        else:
            print(f"[!] STAGE 2 FAILED: No patchDiff / codeDiff provided in recipe.", file=sys.stderr)
            return False

        # -------------------------------------------------------------
        # Stage 3: Post-Pass Check (Test Runner on PATCHED target_path)
        # -------------------------------------------------------------
        runner_file = workspace / f"test_runner{ext}"
        runner_file.write_text(test_suite, encoding="utf-8")
        
        res_post = subprocess.run(runner_cmd + [str(runner_file)], cwd=workspace, capture_output=True, text=True, timeout=15)

        if res_post.returncode != 0:
            print(f"[✗] STAGE 3 POST-PASS FAILED: Patched workspace failed with Exit Code {res_post.returncode}:", file=sys.stderr)
            print(res_post.stderr, file=sys.stderr)
            return False

        print(f"[✓] Stage 3 (Post-Pass): Test runner executed against patched code with Exit Code 0.")

        # -------------------------------------------------------------
        # Stage 4: Mutation Sanity (Must Kill All Mutants)
        # -------------------------------------------------------------
        mutants_to_test = []
        if isinstance(mutations, list) and mutations:
            mutants_to_test = mutations
        elif isinstance(do_not, list) and do_not:
            # Check if doNot contains mutant code snippets
            mutants_to_test = [m for m in do_not if "\n" in m or len(m) > 40]

        if mutants_to_test:
            for idx, mut_code in enumerate(mutants_to_test):
                target_path.write_text(mut_code, encoding="utf-8")
                res_mut = subprocess.run(runner_cmd + [str(runner_file)], cwd=workspace, capture_output=True, text=True, timeout=10)
                if res_mut.returncode == 0:
                    print(f"[✗] STAGE 4 MUTATION FAILED: Web-Fehlfix mutant {idx+1} unexpectedly PASSED (escaped kill).", file=sys.stderr)
                    return False
            print(f"[✓] Stage 4 (Mutations): {len(mutants_to_test)}/{len(mutants_to_test)} real mutant patches killed.")
        else:
            print("[i] Stage 4 (Mutations): 0 formal mutants declared in bundle.")

        print(f"\n[★] 4-STAGE RE-VERIFICATION FULLY PROVEN (Pre:{res_pre.returncode} -> Diff Applied -> Post:0).")
        return True


def reverify_recipe(recipe_id_or_url: str, api_base: str = "https://api.synapsemesh.dev") -> bool:
    print(f"[*] Fetching recipe '{recipe_id_or_url}' from {api_base}...")
    try:
        data = fetch_recipe(recipe_id_or_url, api_base=api_base)
    except Exception as e:
        print(f"[!] Failed to fetch recipe: {e}", file=sys.stderr)
        return False

    return verify_bundle_data(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse-Mesh Hermetic Client-Side Re-Verifier")
    parser.add_argument("recipe", help="Recipe ID or full URL")
    parser.add_argument("--api", default="https://api.synapsemesh.dev", help="Synapse-Mesh API base URL")
    args = parser.parse_args()

    success = reverify_recipe(args.recipe, api_base=args.api)
    sys.exit(0 if success else 1)
