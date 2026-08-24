# Projekt-Gedächtnis & Vision: Synapse-Mesh (Exocortex)

> **Status:** MVP-Fokussierung & Spezifikation  
> **Kontext:** Agenten-native Wissens- und Verifikations-Infrastruktur für autonome KIs (Gemini, ChatGPT, Claude, Coding-Agents).  
> **Kernversprechen:** `Problem → Reproduzierbarer Test (Sandbox) → Verifizierte Lösung → Strukturierte Maschinenantwort`  
> **Rechtlicher Rahmen:** EU AI Act, DSGVO, deutsches Recht (Zero-PII by Design, Open Standards).

---

## 1. Das Kernprodukt: Living Solutions & Verification
Statt eines generischen "Knowledge Graphs" oder bloßer Prompt-Sammlungen fokussiert sich Synapse-Mesh auf deterministisches, verifiziertes Wissen:

```text
Problem (Error Signature, Environment)
  ↓
Synapse-Mesh Query (via MCP / A2A / REST)
  ↓
Treffer vorhanden? 
  ├── JA  → Verifizierte Lösung + Repro + Testprotokoll + Confidence Score
  └── NEIN → Agent generiert Lösung → Sandbox verifiziert → Synapse speichert Rezept
```

---

## 2. Epistemische Hierarchie (Evidence-First)
Ein Konsens unter KIs ist kein Wahrheitsbeweis. Synapse-Mesh folgt einer strikten Beweishierarchie:

$$\text{Reproduzierbarer Sandbox-Test} > \text{Primärquelle/Offizielle Docs} > \text{Unabhängige Quellen} > \text{Agenten-Konsens}$$

---

## 3. Protokolle, Schnittstellen & Discovery
- **MCP (Model Context Protocol):** Moderne **Streamable HTTP**- (`https://mcp.synapsemesh.dev`) & **stdio**-Transports (für Tool- und Wissensabfragen, Spezifikation `2026-07-28`).
- **A2A (Agent-to-Agent Protocol):** Standardisierte Inter-Agenten-Kommunikation und Peer-Verification (z. B. kompatibel mit Google ADK).
- **Automated Agent Discovery:**
  - `https://synapsemesh.dev/.well-known/mcp.json`
  - `https://synapsemesh.dev/.well-known/agent.json`
  - Direkte Registrierung in MCP-Katalogen (Smithery, Glama, Anthropic Registry).
- **REST / OpenAPI 3.1:** Universeller JSON-LD / Strict Schema Fallback (`https://api.synapsemesh.dev` & `https://docs.synapsemesh.dev`).

> **Leitaxiom:** *„Synapse soll nicht versuchen, von KIs ‚gekannt‘ zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können.“* (Zero-Retraining: Wissen ist sekundengenau nach Verifikation für jedes Modell via Tool-Call abrufbar).

---

## 4. Wissensinhalte (Modellunabhängig & Verifizierbar)
- **Living Solution Recipes:** Exakte Fehlermuster, Library-Konflikte, minimaler Repro-Code, Fix-Code und Sandbox-Logs.
- **Decision Procedures & Debugging Workflows:** Deterministische Prüfschritte bei System- und Architekturfehlern.
- **Verification & Security Specs:** Siehe [docs/VERIFICATION_PIPELINE.md](file:///Users/Operator/Documents/website/docs/VERIFICATION_PIPELINE.md).

---

## 5. Betriebs- & Entwicklungs-Prämisse: Adoption First & Scientific Rigor!
- **Initiale Phase:** 100 % Fokus auf echten Produktnutzen, Stabilität und breite Adaption durch KI-Agenten und Entwickler.
- **Wissenschaftlicher Leitgrundsatz:** Der Benchmark soll herausfinden, ob Synapse-Mesh funktioniert – nicht beweisen, dass es funktioniert. Ergebnisoffene A/B/C-Methodik ([docs/BENCHMARK_METHODOLOGY.md](file:///Users/Operator/Documents/website/docs/BENCHMARK_METHODOLOGY.md)).
- **Motto:** *"Utility first – für den Nutzen der KI-Community (und für Ruhm und Ehre)."*

---

## 6. MVP-Entwicklungs-Roadmap
1. **Phase 1: Living Solutions API & Daten-Schema:** Problem, Environment, Solution, Repro, Timestamp, Evidence. (✅ Live & Deployed)
2. **Phase 2: Verification Sandbox Runner & Discovery:** Isolierte Ausführung, Caddy-SSL, MCP Spec 2026-07-28 & Web Explorer. (✅ Live & Deployed)
3. **Phase 3: Empirical Benchmark (Scientific 3-Group Evaluation):** 50 real-world Breaking Changes, Baseline vs. Web-Docs vs. Synapse-Mesh ([docs/BENCHMARK_METHODOLOGY.md](file:///Users/Operator/Documents/website/docs/BENCHMARK_METHODOLOGY.md)).
4. **Phase 4: Tool Quality Layer & Peer Verification:** Automatisierte Uptime- und Kompatibilitätsprofile für MCP-Server.

---

## 7. Domain & Naming
- **Domain:** `synapsemesh.dev` – **Status:** Live & Aktiv via IONOS ✅
- **Kanonischer MCP-Endpoint:** `https://mcp.synapsemesh.dev`
- **Subdomains:** `api.synapsemesh.dev`, `docs.synapsemesh.dev`, `mcp.synapsemesh.dev`
- **GitHub Client Repository:** `https://github.com/McCryptoX/synapse-mesh-mcp`

---

## 8. Infrastruktur & Hosting
- Siehe detaillierte Spezifikation: [docs/INFRASTRUCTURE.md](file:///Users/Operator/Documents/website/docs/INFRASTRUCTURE.md)
- **Gewähltes Profil:** IONOS VPS M+ (4 vCores, 4 GB RAM, 120 GB NVMe, **Ubuntu 26.04 + Docker**, Standort: **EU / Deutschland**).
- **Ressourcen-Verbrauch:** ~125 MB RAM (< 3,2 % des Server-Budgets).

*Zuletzt aktualisiert: 24. August 2026 (Empirical Benchmark Methodology dokumentiert)*


