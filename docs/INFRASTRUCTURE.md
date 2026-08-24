# Infrastruktur-Anforderungen: Synapse-Mesh (Exocortex)

## 1. Benötigter Server-Typ: Linux vServer (VPS) mit SSH-Zugriff

Reiner Webspace (Shared Hosting) reicht **nicht** aus. Für die Anforderungen von Synapse-Mesh ist ein vollwertiger **Linux vServer (VPS)** (z. B. Strato Linux V-Server, Hetzner Cloud oder Netcup) mit **SSH-Zugriff und Root-/Sudo-Rechten** zwingend erforderlich.

---

## 2. Warum Shared Webspace nicht ausreicht

| Anforderung | Shared Webspace | Linux vServer (VPS) |
| :--- | :--- | :--- |
| **Laufzeit-Prozesse** | ❌ Bricht nach 30–60s ab (PHP-Timeout) | ✅ Permanente Daemons (FastAPI, Rust, Go, Python) |
| **Protokolle (MCP / Streams)** | ❌ Meist nur HTTP/1.1 Request-Response | ✅ WebSockets, SSE & gRPC für Agenten-Echtzeit |
| **Sandbox-Ausführung** | ❌ Keine Container-Unterstützung | ✅ Docker / Podman / WASM für sichere Code-Tests |
| **Vektor- & Graph-Datenbanken**| ❌ Nur Standard-MySQL / MariaDB | ✅ Qdrant, PGVector, Chroma, Meilisearch |
| **Autonome Administration** | ❌ Nur FTP / Web-Panel | ✅ Voller SSH-Zugriff für Deployment, Logs & CI/CD |

---

## 3. Empfohlene Mindestspezifikationen (z. B. für den Einstieg)
- **Betriebssystem:** Ubuntu 24.04 LTS oder Debian 12
- **CPU:** Mindestens 2–4 vCores
- **RAM:** Mindestens 4–8 GB RAM (für Vector-Indexierung & Container-Sandboxing)
- **Speicher:** 40–80 GB NVMe/SSD
- **Netzwerk:** Feste IPv4/IPv6, unlimitierter Traffic, SSL via Let's Encrypt / Caddy

---

## 4. Bereitgestellte Basis-Dienste
- **Reverse Proxy:** Caddy oder Traefik (automatisches SSL & HTTP/3)
- **Container Runtime:** Docker Engine + Docker Compose
- **Database Layer:** PostgreSQL mit `pgvector` oder Qdrant
- **Application Layer:** FastAPI / Rust Daemon für die semantische MCP-Schnittstelle
