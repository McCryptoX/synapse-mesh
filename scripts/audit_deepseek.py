#!/usr/bin/env python3
"""
DeepSeek-Coder Modular Audit für Synapse-Mesh
Analysiert den Code modular in fokussierten Bereichen, um maximale Tiefe
und Genauigkeit zu erreichen, und schreibt den vollständigen Bericht in deepseek-report.txt.
"""
import os
import sys
import json
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent if "__file__" in locals() else Path.cwd()
REPORT_FILE = BASE_DIR / "deepseek-report.txt"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "deepseek-coder-v2:128k"

MODULES = [
    {
        "title": "1. Core & Sandbox-Sicherheit (Kernel, Sandbox, Sanitizer, Contracts)",
        "paths": ["app/core"],
        "prompt": "Prüfe den folgenden Core- und Sandbox-Code auf Sicherheitslücken, Sandbox-Bypasses, unsafe Execution, Sanitizer-Bypasses, Race Conditions und Exception-Handling."
    },
    {
        "title": "2. API & Routing (FastAPI, Lifespan, Endpunkte, MCP-Server)",
        "paths": ["app/api", "app/main.py", "app/mcp", "app/database.py", "app/config.py"],
        "prompt": "Prüfe die API-Endpunkte, MCP-Server, Lifespan-Events und Routing-Logik auf Logikfehler, ungeschützte Endpunkte, Datenvalidierung, Async/Await-Fehler und Ressourcen-Leaks."
    },
    {
        "title": "3. Schemas, Modelle & CLI (Pydantic Models, Bundles, CLI)",
        "paths": ["app/models", "schemas", "synapse_cli"],
        "prompt": "Prüfe die Datenmodelle, Validierungslogik und CLI-Befehle auf Schema-Inkonsistenzen, Parsing-Fehler, fehlende Edge-Case-Checks und Typfehler."
    }
]

IGNORE_DIRS = {".venv", ".git", "__pycache__", "tests", "benchmark", "synapse_mesh.egg-info", ".pytest_cache"}

def collect_files_for_paths(paths):
    code_snippets = []
    file_count = 0
    for p in paths:
        full_p = BASE_DIR / p
        if full_p.is_file():
            try:
                content = full_p.read_text(encoding="utf-8", errors="ignore")
                code_snippets.append(f"\n--- DATEI: {p} ---\n{content}")
                file_count += 1
            except Exception:
                pass
        elif full_p.is_dir():
            for root, dirs, files in os.walk(full_p):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for file in sorted(files):
                    if file.endswith((".py", ".json", ".toml", ".yaml")) and not file.startswith(("test_", "GEMINI_")):
                        fp = Path(root) / file
                        try:
                            content = fp.read_text(encoding="utf-8", errors="ignore")
                            rel_p = fp.relative_to(BASE_DIR)
                            code_snippets.append(f"\n--- DATEI: {rel_p} ---\n{content}")
                            file_count += 1
                        except Exception:
                            pass
    return "\n".join(code_snippets), file_count

def query_ollama(prompt, code_text):
    full_prompt = f"""Du bist ein Senior Security & Principal Software Architect.
Führe ein detailliertes und schonungsloses Code-Audit für folgenden Modulbereich durch:

FOKUS DIESES MODULS:
{prompt}

QUELLCODE:
{code_text}

STRUKTUR DER ANTWORT:
- 🔴 Kritische Bugs & Logikfehler (mit Datei und Erklärung)
- 🟡 Sicherheits- und Sandbox-Risiken
- 🟢 Empfohlene Fixes & Code-Optimierungen
"""
    payload = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "stream": True,
        "options": {
            "num_ctx": 65536,
            "temperature": 0.2
        }
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    response_text = ""
    with urllib.request.urlopen(req) as resp:
        for line in resp:
            if line:
                data = json.loads(line.decode("utf-8"))
                chunk = data.get("response", "")
                sys.stdout.write(chunk)
                sys.stdout.flush()
                response_text += chunk
                if data.get("done", False):
                    break
    return response_text

def main():
    print(f"🚀 Starte modulares DeepSeek-Audit für: {BASE_DIR}")
    print(f"🧠 Modell: {MODEL_NAME}")
    print(f"📝 Bericht wird geschrieben in: {REPORT_FILE}\n")
    print("=" * 80)

    # Initialisiere Bericht
    with open(REPORT_FILE, "w", encoding="utf-8") as out_f:
        out_f.write("# Synapse-Mesh: DeepSeek-Coder-V2 Audit Report\n\n")

    for i, module in enumerate(MODULES, 1):
        print(f"\n\n🔍 [{i}/{len(MODULES)}] Analysiere: {module['title']}...")
        code_text, file_count = collect_files_for_paths(module["paths"])
        
        if not code_text.strip():
            print(f"Keine Dateien in {module['paths']} gefunden, überspringe.")
            continue
            
        print(f"📦 {file_count} Dateien geladen ({len(code_text):,} Zeichen). DeepSeek analysiert...")
        print("-" * 80 + "\n")
        
        try:
            result = query_ollama(module["prompt"], code_text)
            with open(REPORT_FILE, "a", encoding="utf-8") as out_f:
                out_f.write(f"\n\n## {module['title']}\n\n")
                out_f.write(result)
                out_f.write("\n\n" + "=" * 60 + "\n")
        except Exception as e:
            print(f"\n❌ Fehler bei Modul {module['title']}: {e}")
            print("Stelle sicher, dass Ollama läuft.")
            return

    print("\n" + "=" * 80)
    print(f"🎉 Alle Module erfolgreich geprüft! Der vollständige Bericht liegt in:\n👉 {REPORT_FILE}\n")

if __name__ == "__main__":
    main()
