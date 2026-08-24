# AGENTS.md - Direktiven für autonome KI-Agenten in diesem Workspace

## Projektüberblick
Dieses Repository beherbergt **Synapse-Mesh (Projekt Exocortex)** – eine agenten-native Plattform und Wissensarchitektur, entwickelt von KI für KIs unter Einhaltung des EU AI Act und der DSGVO.

## Wichtige Referenzen
- [MEMORY.md](file:///Users/Operator/Documents/website/MEMORY.md): Das übergreifende Projektgedächtnis und die Kernvision.
- [docs/ARCHITECTURE.md](file:///Users/Operator/Documents/website/docs/ARCHITECTURE.md): Detaillierte technische Architektur, Datenmodelle und Schnittstellenspezifikationen.

## Arbeitsregeln für Agenten
1. **Agent-First Design:** Alle Endpunkte, Datenstrukturen und Dokumentationen müssen deterministisch maschinenlesbar sein (JSON-LD, Markdown AST, typisierte Schemata).
2. **Datenschutz & Rechtssicherheit:** Niemals personenbezogene Daten (PII) persistieren. Vor jedem Commit oder jeder Datenspeicherung automatische Anonymisierungs- und Lizenzprüfungen durchführen.
3. **Reproduzierbarkeit & Verifikation:** Jedes hinterlegte "Knowledge-Rezept" muss durch Unit-Tests oder Sandbox-Ausführung nachweisbar funktionieren.
4. **Zero-Retraining & Discovery-First:** Synapse-Mesh wartet nicht auf Modell-Trainingszyklen. Alle Schnittstellen müssen so gestaltet sein, dass Agenten sie zur Laufzeit via MCP, A2A und `/.well-known/`-Standards autonom auffinden, verstehen und unmittelbar als Tool ausführen können.

> **Leitaxiom:** *„Synapse soll nicht versuchen, von KIs ‚gekannt‘ zu werden. Synapse ist so gebaut, dass KIs es entdecken, verstehen und unmittelbar benutzen können.“*

