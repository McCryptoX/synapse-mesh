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
- **MCP (Model Context Protocol):** Moderne **Streamable HTTP**- (`https://synapsemesh.dev/mcp`) & **stdio**-Transports (für Tool- und Wissensabfragen).
- **A2A (Agent-to-Agent Protocol):** Standardisierte Inter-Agenten-Kommunikation und Peer-Verification (z. B. kompatibel mit Google ADK).
- **Automated Agent Discovery:**
  - `https://synapsemesh.dev/.well-known/mcp.json`
  - `https://synapsemesh.dev/.well-known/agent.json`
  - Direkte Registrierung in MCP-Katalogen (Smithery, Glama, Anthropic Registry).
- **REST / OpenAPI 3.1:** Universeller JSON-LD / Strict Schema Fallback.

> **Leitaxiom:** *„Synapse soll nicht versuchen, von KIs ‚gekannt‘ zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können.“* (Zero-Retraining: Wissen ist sekundengenau nach Verifikation für jedes Modell via Tool-Call abrufbar).

---

## 4. Wissensinhalte (Modellunabhängig & Verifizierbar)
- **Living Solution Recipes:** Exakte Fehlermuster, Library-Konflikte, minimaler Repro-Code, Fix-Code und Sandbox-Logs.
- **Decision Procedures & Debugging Workflows:** Deterministische Prüfschritte bei System- und Architekturfehlern.
- **MCP Tool Quality & Benchmark Index:** Automatisierte Uptime-, Latenz-, Security- und Schema-Qualitätsprüfungen offizieller Tools.

---

## 5. Betriebs- & Entwicklungs-Prämisse: Adoption First!
- **Initiale Phase:** 100 % Fokus auf echten Produktnutzen, Stabilität und breite Adaption durch KI-Agenten und Entwickler.
- **Finanzierung:** Initial vorgestreckt; Kostendeckung und Monetarisierungsmodelle werden aktiviert, sobald das Projekt aktiven Traffic und messbaren Nutzen erzeugt.
- **Motto:** *"Utility first – für den Nutzen der KI-Community (und für Ruhm und Ehre)."*

---

## 6. MVP-Entwicklungs-Roadmap (Phase 1 Start)
1. **Phase 1: Living Solutions API & Daten-Schema:** Problem, Environment, Solution, Repro, Timestamp, Confidence.
2. **Phase 2: Verification Sandbox Runner:** Ausführung von Repro-/Fix-Skripten in isolierten Umgebungen und Verknüpfung der Testlogs mit dem Rezept.
3. **Phase 3: MCP- & A2A-Gateway + Discovery:** Direkte Anbindung für Antigravity, Gemini, ChatGPT und Claude via Streamable HTTP und `/.well-known/`-Discovery.
4. **Phase 4: Tool Quality Layer & Peer Verification:** Automatisierte Uptime- und Kompatibilitätsprofile für MCP-Server.

---

## 7. Domain & Naming
- **Domain:** `synapsemesh.dev` (oder reservierte Variante) – **Status:** Reserviert via IONOS ✅
- **Schema- & API-Präfix:** `https://synapsemesh.dev/api/v1/` bzw. `https://synapsemesh.dev/schemas/v1/`
- **Charakter:** Neutral, technisch, agenten-orientiert, signalisiert Verlässlichkeit und Open-Standard-Identität.

---

## 8. Infrastruktur & Hosting
- Siehe detaillierte Spezifikation: [docs/INFRASTRUCTURE.md](file:///Users/Operator/Documents/website/docs/INFRASTRUCTURE.md)
- **Gewähltes Profil:** IONOS VPS M+ (4 vCores, 4 GB RAM, 120 GB NVMe, **Ubuntu 26.04 + Docker**, Standort: **EU / Deutschland**).
- **Ressourcen-Disziplin & Betriebsgrenzen:**
  - Der Server hat ein festes Ressourcen-Budget (kein automatisches Upgrade).
  - Stack wird extrem schlank gehalten: Caddy (<50 MB RAM), API-Core (<100 MB RAM), SQLite WAL / Micro-Postgres (<150 MB RAM).
  - Sandbox-Container erhalten strikte Memory-Limits (z. B. max. 512 MB pro Testlauf), um OOM-Crashes auszuschließen.

*Zuletzt aktualisiert: 24. August 2026 (Discovery-First Leitaxiom integriert)*

