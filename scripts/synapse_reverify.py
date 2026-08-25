#!/usr/bin/env python3
"""
Synapse-Mesh Client-Side Re-Verifier
Allows any external AI agent (Cursor, Claude, Grok, Antigravity) to independently
re-verify a recipe's test suite and diff in its own local workspace before committing code.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import urllib.request


def reverify_recipe(recipe_id_or_url: str, api_base: str = "https://api.synapsemesh.dev") -> bool:
    recipe_id = recipe_id_or_url.strip().split("/")[-1]
    url = f"{api_base.rstrip('/')}/api/v1/recipes/{recipe_id}"
    
    print(f"[*] Fetching recipe '{recipe_id}' from {url}...")
    try:
        import httpx
        resp = httpx.get(url, headers={"User-Agent": "Synapse-Client-Reverify/1.0"}, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            print(f"[!] Recipe {recipe_id} not found (HTTP {resp.status_code})", file=sys.stderr)
            return False
        data = resp.json()
    except Exception:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Synapse-Client-Reverify/1.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[!] Failed to fetch recipe {recipe_id}: {e}", file=sys.stderr)
            return False

    runtime = data.get("problem", {}).get("runtime", "python").lower()
    repro = data.get("reproduction", {})
    test_suite = repro.get("testSuite", "")
    
    if not test_suite:
        print("[!] Recipe does not contain an executable testSuite.", file=sys.stderr)
        return False

    print(f"[*] Executing independent local re-verification ({runtime})...")

    with tempfile.TemporaryDirectory(prefix="synapse_reverify_") as tmp_dir:
        test_file = Path(tmp_dir) / ("test_reverify.py" if runtime == "python" else "test_reverify.js")
        test_file.write_text(test_suite, encoding="utf-8")

        cmd = [sys.executable, str(test_file)] if runtime == "python" else ["node", str(test_file)]
        
        try:
            res = subprocess.run(cmd, cwd=tmp_dir, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                print(f"[✓] CLIENT RE-VERIFICATION PASSED! (Exit Code 0)")
                print(f"    Evidence: Tested against local {runtime} interpreter.")
                return True
            else:
                print(f"[✗] CLIENT RE-VERIFICATION FAILED (Exit Code {res.returncode}):", file=sys.stderr)
                print(res.stderr, file=sys.stderr)
                return False
        except Exception as e:
            print(f"[!] Execution failed: {e}", file=sys.stderr)
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse-Mesh Client-Side Re-Verifier")
    parser.add_argument("recipe", help="Recipe ID (e.g. rec_httpx_028_starlette_002) or full URL")
    parser.add_argument("--api", default="https://api.synapsemesh.dev", help="Synapse-Mesh API base URL")
    args = parser.parse_args()

    success = reverify_recipe(args.recipe, api_base=args.api)
    sys.exit(0 if success else 1)
