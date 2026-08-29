#!/usr/bin/env python3
"""
Synapse-Mesh trusted-input client-side re-verifier
Supports both Golden Compatibility Bundle v1.0.0 and Legacy Recipe Schemas:
  Stage 1: Pre-Fail Check (Unpatched workspace executes repro -> must fail and match regex signature)
  Stage 2: Patch Application (Applies unified diff directly to targetFile)
  Stage 3: Post-Pass Check (Test suite executes on PATCHED workspace -> must exit 0)
  Stage 4: Mutation Sanity (Each mutant unified diff applied to clean workspace -> must fail)
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from importlib.metadata import PackageNotFoundError, version as installed_version

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

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

    # 2. Arbitrary URLs are not an acceptable implicit code source. Download,
    # inspect, and pass a local file instead.
    if target.startswith("http://") or target.startswith("https://"):
        raise RuntimeError("Remote bundle URLs are disabled; inspect the JSON and pass a trusted local file")

    bundle_id = target.split("/")[-1]
    if not re.fullmatch(r"bundle_[a-z0-9_-]{3,120}", bundle_id):
        raise RuntimeError("Expected a curated bundle ID or a trusted local JSON file")
    url = f"{api_base.rstrip('/')}/api/v1/bundles/{bundle_id}"

    if httpx:
        resp = httpx.get(url, headers={"User-Agent": "Synapse-Client-Reverify/1.0"}, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            raise RuntimeError(f"Bundle '{target}' not found (HTTP {resp.status_code})")
        if len(resp.content) > 2_000_000:
            raise RuntimeError("Bundle response exceeds the 2 MB client limit")
        return resp.json()
    else:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Synapse-Client-Reverify/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            payload = resp.read(2_000_001)
            if len(payload) > 2_000_000:
                raise RuntimeError("Bundle response exceeds the 2 MB client limit")
            return json.loads(payload.decode("utf-8"))


def _safe_workspace_path(workspace_dir: Path, relative_path: str) -> Optional[Path]:
    """Resolve an untrusted bundle path without permitting traversal or absolutes."""
    try:
        rel = Path(relative_path)
        root = workspace_dir.resolve()
        resolved = (root / rel).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if rel.is_absolute() or ".." in rel.parts or resolved == root or root not in resolved.parents:
        return None
    return resolved


def _diff_path(value: str) -> str:
    token = value.strip().split("\t", 1)[0]
    if token.startswith(("a/", "b/")):
        token = token[2:]
    return token


def _line_equal(left: str, right: str) -> bool:
    return left.rstrip("\r\n") == right.rstrip("\r\n")


def apply_patch_unified(target_file: Path, patch_diff: str, workspace_dir: Path) -> bool:
    """Apply one strict unified diff to one target file.

    Plain replacement text, malformed hunks, path changes, missing context and
    partially applied patches are rejected.  This intentionally has no
    fail-open "write the supplied text" fallback.
    """
    if not patch_diff or len(patch_diff.encode("utf-8")) > 1024 * 1024:
        return False
    workspace_root = workspace_dir.resolve()
    try:
        target_rel = target_file.resolve().relative_to(workspace_root).as_posix()
    except ValueError:
        return False
    safe_target = _safe_workspace_path(workspace_root, target_rel)
    if safe_target is None or safe_target != target_file.resolve() or not safe_target.is_file():
        return False

    lines = patch_diff.splitlines(keepends=True)
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        return False
    try:
        expected_rel = safe_target.relative_to(workspace_root).as_posix()
    except ValueError:
        return False
    if _diff_path(lines[0][4:]) != expected_rel or _diff_path(lines[1][4:]) != expected_rel:
        return False

    original = safe_target.read_text(encoding="utf-8").splitlines(keepends=True)
    result: List[str] = []
    source_index = 0
    index = 2
    saw_hunk = False
    header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    while index < len(lines):
        header = header_re.match(lines[index])
        if not header:
            return False
        saw_hunk = True
        old_start = int(header.group(1))
        old_count = int(header.group(2) or "1")
        new_count = int(header.group(4) or "1")
        requested_index = 0 if old_start == 0 else old_start - 1
        if requested_index < source_index or requested_index > len(original):
            return False
        result.extend(original[source_index:requested_index])
        source_index = requested_index
        index += 1
        consumed_old = 0
        produced_new = 0

        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line.startswith("\\ No newline at end of file"):
                index += 1
                continue
            if not line or line[0] not in (" ", "+", "-"):
                return False
            marker, content = line[0], line[1:]
            if marker in (" ", "-"):
                if source_index >= len(original) or not _line_equal(original[source_index], content):
                    return False
                if marker == " ":
                    result.append(original[source_index])
                    produced_new += 1
                source_index += 1
                consumed_old += 1
            if marker == "+":
                result.append(content)
                produced_new += 1
            index += 1

        if consumed_old != old_count or produced_new != new_count:
            return False

    if not saw_hunk:
        return False
    result.extend(original[source_index:])
    rendered = "".join(result)
    if rendered == "".join(original):
        return False
    safe_target.write_text(rendered, encoding="utf-8")
    return True


def bundle_uses_real_package(bundle: dict) -> bool:
    """Conservative static provenance gate used before any execution."""
    scope = bundle.get("scope") or {}
    verification = bundle.get("verification") or {}
    package = str(scope.get("package") or "").lower()
    runtime = str(scope.get("runtime") or "").lower()
    blob = "\n".join(
        [*(verification.get("workspaceFiles") or {}).values(),
         str(verification.get("reproductionScript") or ""),
         str(verification.get("testSuite") or "")]
    )
    lowered = blob.lower()
    if re.search(r"\bclass\s+mock\w*\b|\bmockapp\b|const\s+reactdom\s*=\s*\{\s*\}", blob, re.IGNORECASE):
        return False
    if package == "python":
        return runtime == "python" and "import datetime" in lowered
    aliases = {
        "langchain-core": "langchain_core",
        "pydantic-settings": "pydantic_settings",
        "next": "next",
    }
    import_name = aliases.get(package, package.replace("-", "_"))
    if not import_name or runtime not in {"python", "node", "nodejs", "javascript", "typescript"}:
        return False
    if runtime == "python":
        return bool(re.search(rf"(?:^|\n)\s*(?:from|import)\s+{re.escape(import_name)}\b", blob))
    if package == "next":
        return all(token in lowered for token in ("spawnsync", "nextbin", "nextpackage", "dependencymodules"))
    if package == "typescript":
        return "tsc" in lowered or "typescript" in lowered
    escaped = re.escape(import_name)
    return bool(
        re.search(rf"require\s*\(\s*['\"]{escaped}(?:/[^'\"]*)?['\"]\s*\)", blob)
        or re.search(rf"from\s+['\"]{escaped}(?:/[^'\"]*)?['\"]", blob)
        or re.search(rf"node_modules[/\\]{escaped}(?:[/\\]|$)", blob)
    )


def bundle_has_recorded_verification_contract(bundle: dict) -> bool:
    """Validate recorded four-stage metadata without executing bundle code.

    This gate is intentionally weaker than a fresh re-verification: it proves
    only that the curated record contains the required evidence shape and a
    real-package fixture. It is the single promotion gate used by API loading,
    SQLite synchronization, and MCP publication.
    """
    if not isinstance(bundle, dict) or bundle.get("schemaVersion") != "1.0.0":
        return False
    if bundle.get("status") not in ("VERIFIED", "DRAFT", "CANDIDATE", "PROVISIONAL", "UNVERIFIED") or not bundle_uses_real_package(bundle):
        return False

    bundle_id = bundle.get("bundleId")
    if not isinstance(bundle_id, str) or not re.fullmatch(r"(?:bundle|draft)_[a-z0-9_-]{3,120}", bundle_id):
        return False

    scope = bundle.get("scope") or {}
    fingerprint = bundle.get("fingerprint") or {}
    patch = bundle.get("patch") or {}
    verification = bundle.get("verification") or {}
    provenance = bundle.get("provenance") or {}
    target_file = patch.get("targetFile")
    workspace_files = verification.get("workspaceFiles") or {}
    mutations = verification.get("mutations") or []

    if not all(
        (
            isinstance(scope.get("package"), str) and bool(scope["package"].strip()),
            isinstance(scope.get("runtime"), str) and bool(scope["runtime"].strip()),
            isinstance(scope.get("runtimeVersion"), str) and bool(scope["runtimeVersion"].strip()),
            isinstance(scope.get("affectedVersionRange"), str) and bool(scope["affectedVersionRange"].strip()),
            isinstance(fingerprint.get("errorSignature"), str) and bool(fingerprint["errorSignature"].strip()),
            isinstance(target_file, str) and _safe_workspace_path(Path("/tmp/synapse-contract-root"), target_file) is not None,
            isinstance(workspace_files, dict) and target_file in workspace_files,
            isinstance(patch.get("pinnedDependencies"), dict) and bool(patch["pinnedDependencies"]),
            isinstance(verification.get("reproductionScript"), str) and bool(verification["reproductionScript"].strip()),
            isinstance(verification.get("testSuite"), str) and bool(verification["testSuite"].strip()),
            isinstance(verification.get("expectedPreExit"), int)
            and verification["expectedPreExit"] not in (-1, 0),
            verification.get("expectedPostExit") == 0,
            isinstance(provenance.get("verifiedAt"), str) and bool(provenance["verifiedAt"].strip()),
        )
    ):
        return False

    sources = provenance.get("primarySources") or []
    if not isinstance(sources, list) or not sources or not all(
        isinstance(source, str) and source.startswith(("https://", "http://")) for source in sources
    ):
        return False

    main_diff = patch.get("unifiedDiff")
    if not isinstance(main_diff, str) or len(main_diff.encode("utf-8")) > 1024 * 1024:
        return False
    main_lines = main_diff.splitlines()
    if len(main_lines) < 3 or not main_lines[0].startswith("--- ") or not main_lines[1].startswith("+++ "):
        return False
    if _diff_path(main_lines[0][4:]) != target_file or _diff_path(main_lines[1][4:]) != target_file:
        return False

    if not isinstance(mutations, list) or len(mutations) < 2:
        return False
    mutation_ids: set[str] = set()
    mutation_diffs: set[str] = set()
    for mutation in mutations:
        if not isinstance(mutation, dict):
            return False
        mutation_id = mutation.get("id")
        mutation_diff = mutation.get("unifiedDiff")
        if not isinstance(mutation_id, str) or not mutation_id or mutation_id in mutation_ids:
            return False
        if not isinstance(mutation_diff, str) or not mutation_diff or mutation_diff in mutation_diffs:
            return False
        lines = mutation_diff.splitlines()
        if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
            return False
        if _diff_path(lines[0][4:]) != target_file or _diff_path(lines[1][4:]) != target_file:
            return False
        mutation_ids.add(mutation_id)
        mutation_diffs.add(mutation_diff)
    return True


def _verification_env(workspace: Path) -> Dict[str, str]:
    allowed = {"PATH", "LANG", "LC_ALL", "TZ", "NODE_PATH", "SYNAPSE_DEPENDENCY_ROOT"}
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update({
        "HOME": str(workspace),
        "TMPDIR": str(workspace),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    env.setdefault("SYNAPSE_DEPENDENCY_ROOT", str(workspace))
    return env


def _pin_matches(actual: str, declared: str) -> bool:
    """Accept an exact version or a valid PEP 440 constraint; reject ambiguity."""
    value = str(declared or "").strip()
    if not value:
        return False
    try:
        if value.startswith(("<", ">", "=", "!", "~")) or "," in value:
            return Version(actual) in SpecifierSet(value)
        return Version(actual) == Version(value.lstrip("v"))
    except (InvalidSpecifier, InvalidVersion, TypeError, ValueError):
        return False


def _python_pins_match(pins: Dict[str, str]) -> bool:
    for package, declared in pins.items():
        if package.lower() == "python":
            actual = platform.python_version()
        else:
            try:
                actual = installed_version(package)
            except PackageNotFoundError:
                return False
        if not _pin_matches(actual, declared):
            return False
    return True


def verify_golden_bundle(bundle: dict) -> bool:
    """Execute the strict workspace/diff contract for a trusted local bundle.

    Callers must not pass public or remotely supplied code on a server.  This
    function validates evidence semantics; it is not a hostile-code boundary.
    """
    bundle_id = bundle.get("bundleId") or bundle.get("id", "unknown")
    scope = bundle.get("scope", {})
    runtime = scope.get("runtime", "python").lower()
    
    fp = bundle.get("fingerprint", {})
    error_sig = fp.get("errorSignature") or ""
    sig_regex = fp.get("regex") or ""
    
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

    if (
        bundle.get("schemaVersion") != "1.0.0"
        or not isinstance(ws_files, dict)
        or not ws_files
        or len(ws_files) > 64
        or not repro_script
        or not test_suite
        or not error_sig
        or expected_pre_exit == 0
        or expected_post_exit != 0
    ):
        print("[!] UNVERIFIED: bundle is missing required fail-closed contract fields.", file=sys.stderr)
        return False
    if not bundle_uses_real_package(bundle):
        print("[!] UNVERIFIED: workspace does not demonstrate the declared real package/compiler.", file=sys.stderr)
        return False
    if len(mutations) < 2:
        print("[!] UNVERIFIED: at least two mutant diffs are required.", file=sys.stderr)
        return False
    if runtime == "python" and (not pinned_deps or not _python_pins_match(pinned_deps)):
        print("[!] UNVERIFIED: installed Python dependency versions do not match every declared pin.", file=sys.stderr)
        return False
    recorded_patch_hash = patch.get("sha256")
    if recorded_patch_hash and hashlib.sha256(patch_diff.encode("utf-8")).hexdigest() != recorded_patch_hash:
        print("[!] UNVERIFIED: unified diff digest mismatch.", file=sys.stderr)
        return False

    ext = ".py" if runtime == "python" else ".js"
    if runtime == "python":
        runner_cmd = [sys.executable]
    elif runtime in ("nodejs", "node", "javascript", "typescript"):
        node_bin = shutil.which("node")
        if not node_bin:
            print(f"[!] UNVERIFIED: '{runtime}' runtime executable not found on host.", file=sys.stderr)
            return False
        runner_cmd = [node_bin]
    else:
        print(f"[!] UNVERIFIED: unsupported runtime '{runtime}'.", file=sys.stderr)
        return False

    with tempfile.TemporaryDirectory(prefix="synapse_golden_ws_") as tmp_dir:
        workspace = Path(tmp_dir)
        
        timeout_sec = float(verif.get("timeoutMs", 30000)) / 1000.0
        env = _verification_env(workspace)

        def materialize_workspace():
            for child in workspace.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            for rel_p, content in ws_files.items():
                if not isinstance(content, str) or len(content.encode("utf-8")) > 1024 * 1024:
                    raise ValueError("unsafe workspace content")
                dest = _safe_workspace_path(workspace, rel_p)
                if dest is None:
                    raise ValueError("unsafe workspace path")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")

        try:
            target_path = _safe_workspace_path(workspace, target_file_rel)
        except (TypeError, ValueError):
            target_path = None
        if target_path is None or target_file_rel not in ws_files:
            print("[!] UNVERIFIED: target file is outside or absent from the declared workspace.", file=sys.stderr)
            return False

        # -------------------------------------------------------------
        # Stage 1: Pre-Fail Validation (Unpatched Workspace)
        # -------------------------------------------------------------
        try:
            materialize_workspace()
        except ValueError:
            print("[!] UNVERIFIED: unsafe workspace materialization request.", file=sys.stderr)
            return False
        repro_runner = workspace / f"repro_runner{ext}"
        repro_runner.write_text(repro_script, encoding="utf-8")

        res_pre = subprocess.run(runner_cmd + [str(repro_runner)], cwd=workspace, capture_output=True, text=True, timeout=timeout_sec, env=env)
        combined_pre = res_pre.stdout + "\n" + res_pre.stderr

        if res_pre.returncode == 0 or res_pre.returncode != expected_pre_exit:
            print(f"[✗] STAGE 1 PRE-FAIL FAILED: Unpatched workspace exited with 0 (bug not triggered).", file=sys.stderr)
            return False

        # Exception-class gate precedes substring/regex matching.
        from app.core.signature_matcher import SignatureMatcher
        expected_class = SignatureMatcher.extract_structure(error_sig).get("exc_class")
        observed_class = SignatureMatcher.extract_structure(combined_pre).get("exc_class")
        if expected_class and observed_class and expected_class != observed_class:
            print("[✗] STAGE 1 PRE-FAIL FAILED: observed exception class differs from the fingerprint.", file=sys.stderr)
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

            # Run the same test driver on the independently mutated workspace.
            test_runner = workspace / f"test_runner{ext}"
            test_runner.write_text(test_suite, encoding="utf-8")
            res_mut = subprocess.run(runner_cmd + [str(test_runner)], cwd=workspace, capture_output=True, text=True, timeout=timeout_sec, env=env)
            if res_mut.returncode == 0:
                print(f"[✗] STAGE 4 MUTATION FAILED: Web-Fehlfix mutant '{mut_id}' unexpectedly PASSED (escaped kill).", file=sys.stderr)
                return False
            else:
                mutants_killed += 1

        print(f"[✓] Stage 4 (Mutations): {mutants_killed}/{len(mutations)} declared mutant diffs killed.")

        # -------------------------------------------------------------
        # Extra guard: independent claim-level variant verification
        # -------------------------------------------------------------
        variants = fp.get("variants", [])
        if variants:
            for v_idx, v in enumerate(variants):
                v_sig = v.get("errorSignature", "")
                v_assert = v.get("preFailAssertion")
                if v_assert:
                    var_runner = workspace / f"variant_runner_{v_idx}{ext}"
                    var_runner.write_text(v_assert, encoding="utf-8")
                    res_var = subprocess.run(runner_cmd + [str(var_runner)], cwd=workspace, capture_output=True, text=True, timeout=timeout_sec, env=env)
                    if res_var.returncode != 0:
                        print(f"[✗] EXTRA GUARD (VARIANTS) FAILED: Variant '{v_sig}' claim assertion failed on real runtime with Exit {res_var.returncode}:\n{res_var.stderr}", file=sys.stderr)
                        return False
            print(f"[✓] Extra guard (claim variants): all {len(variants)} family claims independently reproduced on the real runtime.")

        # -------------------------------------------------------------
        # Extra guard: evidence metadata integrity
        # -------------------------------------------------------------
        from app.core.version_matcher import VersionMatcher
        aff_range = scope.get("affectedVersionRange")
        if not aff_range:
            print(f"[✗] EXTRA GUARD (METADATA INTEGRITY) FAILED: 'scope.affectedVersionRange' must be explicitly declared for {bundle_id}.", file=sys.stderr)
            return False
            
        pkg_name = scope.get("package", "").lower()
        if pkg_name in pinned_deps:
            pinned_ver_str = pinned_deps[pkg_name]
            if not VersionMatcher.check_version_compatibility(pinned_ver_str, aff_range):
                print(f"[✗] EXTRA GUARD (METADATA INTEGRITY) FAILED: Pinned dependency '{pkg_name}=={pinned_ver_str}' violates affectedVersionRange '{aff_range}'.", file=sys.stderr)
                return False
                
        to_ver = scope.get("toVersion")
        if to_ver and not VersionMatcher.check_version_compatibility(to_ver, aff_range):
            print(f"[✗] EXTRA GUARD (METADATA INTEGRITY) FAILED: Scope toVersion '{to_ver}' violates affectedVersionRange '{aff_range}'.", file=sys.stderr)
            return False

        if pkg_name == "python" and scope.get("runtimeVersion"):
            rt_ver = scope.get("runtimeVersion")
            if not VersionMatcher.check_version_compatibility(rt_ver, aff_range):
                print(f"[✗] EXTRA GUARD (METADATA INTEGRITY) FAILED: Scope runtimeVersion '{rt_ver}' violates affectedVersionRange '{aff_range}'.", file=sys.stderr)
                return False

        print(f"[✓] Extra guard (metadata integrity): pinned dependencies ({pinned_deps.get(pkg_name, 'N/A')}) and scope satisfy affectedVersionRange ('{aff_range}').")

        print(f"\n[✓] BUNDLE CONTRACT PASSED: Pre:{res_pre.returncode} -> Diff Applied -> Post:0 -> Mutants:{mutants_killed}/{len(mutations)}.")
        return True


def verify_bundle_data(data: dict) -> bool:
    """Verify only the structured workspace/diff schema.

    Legacy split-script recipes cannot satisfy the current evidence contract and
    are rejected instead of being silently upgraded.
    """
    if "verification" in data and "workspaceFiles" in data.get("verification", {}):
        return verify_golden_bundle(data)
    return False


def reverify_recipe(bundle_target: str, api_base: str = "https://api.synapsemesh.dev") -> bool:
    try:
        data = fetch_bundle(bundle_target, api_base=api_base)
    except Exception as e:
        print(f"[!] Failed to load bundle: {e}", file=sys.stderr)
        return False

    return verify_bundle_data(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse-Mesh Client-Side Re-Verifier for Trusted Bundles")
    parser.add_argument("bundle", help="Bundle ID, local JSON filepath, or full URL")
    parser.add_argument("--api", default="https://api.synapsemesh.dev", help="Synapse-Mesh API base URL")
    args = parser.parse_args()

    success = reverify_recipe(args.bundle, api_base=args.api)
    sys.exit(0 if success else 1)
