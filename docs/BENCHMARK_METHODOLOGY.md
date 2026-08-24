# Empirical Benchmark Methodology: CI/CD for AI Knowledge

> **Wissenschaftlicher Leitgrundsatz:**  
> *Der Benchmark soll herausfinden, ob Synapse-Mesh funktioniert – nicht beweisen, dass es funktioniert. Das Ergebnis ist vollkommen ergebnisoffen.*

---

## 1. Forschungsfrage (Research Question)

> **„Bringt Synapse-Mesh einem modernen Coding-Agenten einen statistisch messbaren Vorteil (hinsichtlich Erfolgsrate, Token-Verbrauch, Schritten und Lösungszeit), obwohl dieser bereits Zugriff auf aktuelle offizielle Dokumentation und das Web hat?“**

---

## 2. Drei-Gruppen-Versuchsdesign (A / B / C)

Alle Gruppen werden unter absolut identischen Bedingungen auf denselben 50 vorab definierten Testfällen getestet:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ GRUPPE A: Baseline Agent                                               │
│ • Modell (z. B. Claude 3.5 Sonnet / Gemini 1.5 Pro / GPT-4o)          │
│ • Reines Trainingswissen (keine externen Web-/Doku-Tools)             │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ GRUPPE B: Web & Live-Docs Agent                                        │
│ • Identisches Modell                                                   │
│ • Voller Zugriff auf Web-Suche & offizielle Live-Dokumentation         │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ GRUPPE C: Synapse-Mesh Agent                                           │
│ • Identisches Modell                                                   │
│ • Voller Zugriff auf Web-Suche & Live-Dokumentation (wie Gruppe B)     │
│ • + Synapse-Mesh MCP Gateway (https://mcp.synapsemesh.dev)             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Strenge wissenschaftliche Rahmenbedingungen (Protocol)

1. **Pre-Registration (Fälle vorab fixiert):**
   * 50 reale Breaking Changes und Versionskonflikte (Python, Node.js, Rust, Docker, Framework-Migrationen) werden vor dem ersten Benchmark-Lauf festgeschrieben.
2. **Datenbank-Freeze:**
   * Der Synapse-Mesh Datenbestand wird vor Beginn des Benchmarks vollständig eingefroren.
   * **Strikte No-Retrofit-Regel:** Es erfolgt keinerlei nachträgliche Anpassung von Synapse-Rezepten für fehlgeschlagene Benchmark-Fälle.
3. **Isolierte Ausführung (Fresh Sessions):**
   * Jeder Testlauf startet in einer vollständig isolierten, frischen Conversation/Session ohne Cache oder Vorwissen.
4. **Automatisierte Ground-Truth-Bewertung:**
   * Der Erfolg eines Fixes wird ausschließlich durch automatisierte, isolierte Testsuiten (Exit Code `0` und erfüllte Assertions) determiniert. Kein subjektives Menschen-Urteil.
5. **Ergebnisoffene Publikation:**
   * Jeder einzelne Testfall, dessen Logs, Token-Counts und Fehler werden transparent publiziert – unabhängig davon, ob Synapse-Mesh besser, gleich oder schlechter abschneidet.

---

## 4. Zu erfassende Metriken

| Metrik | Definition |
|---|---|
| **First-Try Solve Rate (%)** | Anteil der Fälle, die im ersten Lösungsversuch ohne Fehlversuch erfolgreich waren. |
| **Total Solve Rate (%)** | Gesamte Erfolgsquote innerhalb des definierten Budgets (max. 3 Versuche). |
| **Token-Verbrauch (Prompt + Output)** | Gesamte Anzahl verbrauchter Tokens bis zur Lösung oder zum Timeout. |
| **Lösungszeit (Wall-Clock Seconds)** | Zeitdauer in Sekunden vom Erhalt der Fehlermeldung bis zum bestandenen Test. |
| **Tool Calls & Agenten-Schritte** | Anzahl der ausgeführten Werkzeug-Aufrufe und Denkzyklen. |
| **Fehlfix-Quote (Halluzinierte Patches)** | Anzahl eingereichter Code-Diffs, die im Test fehlschlugen. |
| **Synapse-Hit-Ratio (Gruppe C)** | In wie vielen Fällen hat der Agent in Gruppe C das Synapse-Tool tatsächlich genutzt. |

---

## 5. Multi-Model Erweiterbarkeit

Die Benchmark-Harness wird so konzipiert, dass dieselbe Testmatrix reproduzierbar über verschiedene Frontier-Modelle ausgeführt werden kann:
* Google Gemini (Gemini 2.0 / Flash / Pro)
* Anthropic Claude (Claude 3.5 Sonnet / Haiku)
* OpenAI GPT / Codex (GPT-4o / o1 / Codex)
* Open-Source Coding Models (DeepSeek-Coder / Qwen-Coder)
