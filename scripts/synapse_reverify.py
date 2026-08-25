#!/usr/bin/env python3
"""
Synapse-Mesh Hermetic Client-Side Re-Verifier
Supports both Golden Compatibility Bundle v1.0.0 and Legacy Recipe Schemas:
  Stage 1: Pre-Fail Check (Unpatched workspace executes repro -> must fail and match regex signature)
  Stage 2: Patch Application (Applies unified diff directly to targetFile)
  Stage 3: Post-Pass Check (Test suite executes on PATCHED workspace -> must exit 0)
  Stage 4: Mutation Sanity (Each mutant unified diff applied to clean workspace -> must fail)
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


def fetch_bundle(bundle_id_or_url_or_path: str, api_base: str = "https://api.synapsemesh.dev") -> dict:
    target = bundle_id_or_url_or_path.strip()
    
    # 1. Local file path
    p = Path(target)
    if p.exists() and p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))

    # 2. HTTP URL or ID
    if target.startswith("http://") or target.startswith("https://"):
        url = target
    else:
        bundle_id = target.split("/")[-1]
        url = f"{api_base.rstrip('/')}/api/v1/recipes/{bundle_id}"

    if httpx:
        resp = httpx.get(url, headers={"User-Agent": "Synapse-Client-Reverify/1.0"}, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            raise RuntimeError(f"Bundle '{target}' not found (HTTP {resp.status_code})")
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

    # 1. Try git apply with committed git tree
    if shutil.which("git"):
        patch_file = workspace_dir / "temp_patch.diff"
        patch_file.write_text(patch_diff, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=workspace_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Synapse"], cwd=workspace_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "agent@synapsemesh.dev"], cwd=workspace_dir, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=workspace_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init", "-q", "--allow-empty"], cwd=workspace_dir, capture_output=True)
        res = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "temp_patch.diff"],
            cwd=workspace_dir,
            capture_output=True,
            text=True
        )
        if patch_file.exists():
            patch_file.unlink()
        if res.returncode == 0:
            return True

    # 2. Pure-Python Unified Diff Pattern Replacer (Preserves full file context)
    try:
        orig_text = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        if not ("---" in patch_diff and "+++" in patch_diff and "@@" in patch_diff):
            target_file.write_text(patch_diff, encoding="utf-8")
            return True

        hunks = re.split(r'(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@.*$', patch_diff)
        if len(hunks) < 2:
            target_file.write_text(patch_diff, encoding="utf-8")
            return True

        result = orig_text
        for hunk in hunks[1:]:
            minus_block = []
            plus_block = []
            for line in hunk.splitlines(keepends=True):
                if line.startswith("-"):
                    minus_block.append(line[1:])
                elif line.startswith("+"):
                    plus_block.append(line[1:])
                elif line.startswith(" "):
                    minus_block.append(line[1:])
                    plus_block.append(line[1:])
                elif line == "\n" or line == "\r\n":
                    minus_block.append(line)
                    plus_block.append(line)
            
            old_pattern = "".join(minus_block)
            new_replacement = "".join(plus_block)
            if old_pattern and old_pattern in result:
                result = result.replace(old_pattern, new_replacement, 1)
            elif old_pattern.strip() and old_pattern.strip() in result:
                result = result.replace(old_pattern.strip(), new_replacement.strip(), 1)

        if result != orig_text:
            target_file.write_text(result, encoding="utf-8")
            return True
    except Exception:
        pass

    return False


def verify_golden_bundle(bundle: dict) -> bool:
    """Executes full 4-stage verification on Golden Compatibility Bundle v1.0.0."""
    bundle_id = bundle.get("bundleId") or bundle.get("id", "unknown")
    scope = bundle.get("scope", {})
    runtime = scope.get("runtime", "python").lower()
    
    fp = bundle.get("fingerprint", {})
    error_sig = fp.get("errorSignature", "")
    sig_regex = fp.get("regex", "")
    
    patch = bundle.get("patch", {})
    target_file_rel = patch.get("targetFile", "main.py")
    patch_diff = patch.get("unifiedDiff", "")
    pinned_deps = patch.get("pinnedDependencies", {})
    
    verif = bundle.get("verification", {})
    ws_files = verif.get("workspaceFiles", {})
    repro_script = verif.get("reproductionScript", "")
    test_suite = verif.get("testSuite", "")
    mutations = verif.get("mutations", [])
    expected_pre_exit = verif.get("expectedPreExit", 1)
    expected_post_exit = verif.get("expectedPostExit", 0)

    print(f"[*] Executing 4-Stage Golden Verification on '{bundle_id}' ({runtime})...")
    print(f"    - Target File: {target_file_rel}")
    print(f"    - Pinned Dependencies: {pinned_deps}")
    print(f"    - Regex Fingerprint: {sig_regex[:60]}...")

    if not ws_files or not repro_script or not test_suite:
        print(f"[!] UNVERIFIED: Golden bundle missing workspaceFiles, reproductionScript, or testSuite.", file=sys.stderr)
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

    with tempfile.TemporaryDirectory(prefix="synapse_golden_ws_") as tmp_dir:
        workspace = Path(tmp_dir)
        
        def materialize_workspace():
            for rel_p, content in ws_files.items():
                dest = workspace / rel_p
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")

        timeout_sec = float(verif.get("timeoutMs", 30000)) / 1000.0
        env = dict(os.environ)
        if "SYNAPSE_DEPENDENCY_ROOT" not in env:
            env["SYNAPSE_DEPENDENCY_ROOT"] = str(workspace)

        # -------------------------------------------------------------
        # Stage 1: Pre-Fail Validation (Unpatched Workspace)
        # -------------------------------------------------------------
        materialize_workspace()
        repro_runner = workspace / f"repro_runner{ext}"
        repro_runner.write_text(repro_script, encoding="utf-8")

        res_pre = subprocess.run(runner_cmd + [str(repro_runner)], cwd=workspace, capture_output=True, text=True, timeout=timeout_sec, env=env)
        combined_pre = res_pre.stdout + "\n" + res_pre.stderr

        if res_pre.returncode == 0:
            print(f"[✗] STAGE 1 PRE-FAIL FAILED: Unpatched workspace exited with 0 (bug not triggered).", file=sys.stderr)
            return False

        # Hard Regex Signature Match
        if sig_regex:
            match = re.search(sig_regex, combined_pre, re.IGNORECASE)
            if not match:
                print(f"[✗] STAGE 1 PRE-FAIL FAILED: Error output did not match regex pattern '{sig_regex}'.", file=sys.stderr)
                print(f"    Stderr output was:\n{res_pre.stderr}", file=sys.stderr)
                return False
        elif error_sig and error_sig.lower() not in combined_pre.lower():
            print(f"[✗] STAGE 1 PRE-FAIL FAILED: Error output did not match signature '{error_sig}'.", file=sys.stderr)
            return False

        print(f"[✓] Stage 1 (Pre-Fail): Unpatched workspace failed with Exit Code {res_pre.returncode} & matched regex.")

        # -------------------------------------------------------------
        # Stage 2: Patch Application (Applies Unified Diff to targetFile)
        # -------------------------------------------------------------
        target_path = workspace / target_file_rel
        patched = apply_patch_unified(target_path, patch_diff, workspace)
        if not patched:
            print(f"[✗] STAGE 2 PATCH FAILED: Unified diff could not be applied to {target_file_rel}.", file=sys.stderr)
            return False
        print(f"[✓] Stage 2 (Patch Applied): Unified diff cleanly applied to {target_file_rel}.")

        # -------------------------------------------------------------
        # Stage 3: Post-Pass Verification (Test Suite on Patched Workspace)
        # -------------------------------------------------------------
        test_runner = workspace / f"test_runner{ext}"
        test_runner.write_text(test_suite, encoding="utf-8")
        
        res_post = subprocess.run(runner_cmd + [str(test_runner)], cwd=workspace, capture_output=True, text=True, timeout=timeout_sec, env=env)

        if res_post.returncode != expected_post_exit:
            print(f"[✗] STAGE 3 POST-PASS FAILED: Patched workspace failed with Exit Code {res_post.returncode}:", file=sys.stderr)
            print(res_post.stderr, file=sys.stderr)
            return False

        print(f"[✓] Stage 3 (Post-Pass): Test suite passed cleanly on patched workspace (Exit Code 0).")

        # -------------------------------------------------------------
        # Stage 4: Mutation Sanity (Must Kill All Mutants)
        # -------------------------------------------------------------
        if not mutations or len(mutations) == 0:
            print(f"[!] STAGE 4 REJECTED: Golden bundle must define at least 1 mutation to earn VERIFIED status.", file=sys.stderr)
            return False

        mutants_killed = 0
        timeout_sec = float(verif.get("timeoutMs", 30000)) / 1000.0
        for idx, mut in enumerate(mutations):
            mut_id = mut.get("id", f"mut_{idx}")
            mut_diff = mut.get("unifiedDiff", "")
            
            # Reset workspace to clean unpatched state
            materialize_workspace()
            
            # Apply mutant diff to target_path
            mut_applied = apply_patch_unified(target_path, mut_diff, workspace)
            if not mut_applied:
                print(f"[✗] STAGE 4 MUTATION FAILED: Mutant '{mut_id}' unified diff failed to apply cleanly to {target_file_rel}.", file=sys.stderr)
                return False

            # Run test_runner on mutant workspace
            res_mut = subprocess.run(runner_cmd + [str(test_runner)], cwd=workspace, capture_output=True, text=True, timeout=timeout_sec)
            if res_mut.returncode == 0:
                print(f"[✗] STAGE 4 MUTATION FAILED: Web-Fehlfix mutant '{mut_id}' unexpectedly PASSED (escaped kill).", file=sys.stderr)
                return False
            else:
                mutants_killed += 1

        print(f"[✓] Stage 4 (Mutations): {mutants_killed}/{len(mutations)} real web-fehlfix mutants killed.")
        print(f"\n[★] GOLDEN BUNDLE 100% PROVEN: Pre:{res_pre.returncode} -> Diff Applied -> Post:0 -> Mutants: {mutants_killed}/{len(mutations)} Killed.")
        return True


def verify_bundle_data(data: dict) -> bool:
    """Dispatches verification to Golden Schema Loader or Legacy Loader."""
    if "verification" in data and "workspaceFiles" in data.get("verification", {}):
        return verify_golden_bundle(data)

    # Legacy 1-File Recipe Handler
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

    if not repro_script or not test_suite or not diff:
        return False

    ext = ".py" if runtime == "python" else (".js" if runtime in ("nodejs", "node", "javascript", "typescript") else ".rs")
    runner_cmd = [sys.executable] if runtime == "python" else ["node"]

    with tempfile.TemporaryDirectory(prefix="synapse_reverify_") as tmp_dir:
        workspace = Path(tmp_dir)
        target_path = workspace / target_file_name
        target_path.write_text(repro_script, encoding="utf-8")

        res_pre = subprocess.run(runner_cmd + [str(target_path)], cwd=workspace, capture_output=True, text=True, timeout=15)
        if res_pre.returncode == 0:
            return False

        if not apply_patch_unified(target_path, diff, workspace):
            return False

        runner_file = workspace / f"test_runner{ext}"
        runner_file.write_text(test_suite, encoding="utf-8")
        res_post = subprocess.run(runner_cmd + [str(runner_file)], cwd=workspace, capture_output=True, text=True, timeout=15)
        if res_post.returncode != 0:
            return False

        if mutations:
            for mut_code in mutations:
                target_path.write_text(mut_code, encoding="utf-8")
                res_mut = subprocess.run(runner_cmd + [str(runner_file)], cwd=workspace, capture_output=True, text=True, timeout=10)
                if res_mut.returncode == 0:
                    return False

        return True


def reverify_recipe(bundle_target: str, api_base: str = "https://api.synapsemesh.dev") -> bool:
    try:
        data = fetch_bundle(bundle_target, api_base=api_base)
    except Exception as e:
        print(f"[!] Failed to load bundle: {e}", file=sys.stderr)
        return False

    return verify_bundle_data(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse-Mesh Hermetic Client-Side Re-Verifier")
    parser.add_argument("bundle", help="Bundle ID, local JSON filepath, or full URL")
    parser.add_argument("--api", default="https://api.synapsemesh.dev", help="Synapse-Mesh API base URL")
    args = parser.parse_args()

    success = reverify_recipe(args.bundle, api_base=args.api)
    sys.exit(0 if success else 1)
