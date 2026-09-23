# Chainlit Production Server Setup

Diese Anleitung dokumentiert das Setup der GSKI Chainlit-App auf einem Production Server (VPS Linux, Ubuntu 24.04).

## Voraussetzungen

- VPS mit min. 6 vCores, 8 GB RAM, 240 GB SSD
- Ubuntu 24.04
- Domain mit DNS A-Record auf Server-IP
- OpenVPN-Zugang zu LiteLLM (falls extern gehostet)

---

## 1. Server-Grundkonfiguration

### 1.1 Admin-User anlegen (nicht als root arbeiten)

```bash
# Als root
adduser gski-admin
# Passwort vergeben, Rest mit Enter bestätigen

# Sudo-Rechte geben
usermod -aG sudo gski-admin

# Docker-Gruppe geben (nach Docker-Installation)
usermod -aG docker gski-admin

# SSH-Key vom root kopieren
mkdir -p /home/gski-admin/.ssh
cp /root/.ssh/authorized_keys /home/gski-admin/.ssh/
chown -R gski-admin:gski-admin /home/gski-admin/.ssh
chmod 700 /home/gski-admin/.ssh
chmod 600 /home/gski-admin/.ssh/authorized_keys
```

### 1.2 SSH-Sicherheit

```bash
# Password-Login deaktivieren
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config

# root-SSH deaktivieren (nach erfolgreicher Anmeldung als gski-admin!)
sudo nano /etc/ssh/sshd_config
# PermitRootLogin no

sudo systemctl restart sshd
```

### 1.3 Firewall einrichten

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp    # HTTP (für Let's Encrypt)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### 1.4 Automatische Security-Updates

```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 2. Docker installieren

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# WICHTIG: Ausloggen und neu einloggen für Gruppenrechte
exit
ssh gski-admin@server-ip

# Prüfen
docker --version
docker compose version
```

---

## 3. OpenVPN für LiteLLM-Zugang

Falls LiteLLM über VPN erreichbar ist:

```bash
sudo apt install openvpn -y

# VPN-Config kopieren
sudo cp dein-vpn.ovpn /etc/openvpn/client/litellm.conf

# Autostart aktivieren
sudo systemctl enable openvpn-client@litellm
sudo systemctl start openvpn-client@litellm

# Prüfen
ip a | grep tun
curl -s http://10.127.129.0:4000/health
```

---

## 4. Repository klonen

```bash
# Repository klonen
sudo git clone https://github.com/aihpi/pilotprojekt-GrundschutzKI.git /opt/gski
sudo chown -R gski-admin:gski-admin /opt/gski

# In Projektverzeichnis wechseln
cd /opt/gski

# Ggf. spezifischen Branch auschecken
git fetch origin
git checkout feature/14-fix-chainlit-resume-citations-pdf-preview
```

---

## 5. Umgebungsvariablen konfigurieren (.env)

```bash
cd /opt/gski/apps/chainlit
nano .env
```

### Beispiel .env für Production

```dotenv
# LiteLLM (über VPN erreichbar)
LITELLM_BASE_URL=http://10.127.129.0:4000
LITELLM_API_KEY=sk-dein-api-key
CHAT_MODEL=openai/gpt-oss-120b
FALLBACK_CHAT_MODEL=
EMBED_MODEL=openai/octen-embedding-8b

# Native Chainlit persistence + auth
DATABASE_URL=postgresql://chainlit:chainlit@postgres:5432/chainlit
# Secret generieren: openssl rand -hex 32
CHAINLIT_AUTH_SECRET=hier-dein-generiertes-secret
CHAINLIT_AUTH_USERNAME=admin
CHAINLIT_AUTH_PASSWORD=sicheres-passwort
CHAINLIT_INIT_DB=true

# GitHub OAuth
# Callback URL in GitHub anpassen: https://deine-domain.de/auth/oauth/github/callback
OAUTH_GITHUB_CLIENT_ID=deine-client-id
OAUTH_GITHUB_CLIENT_SECRET=dein-client-secret

# Qdrant (Container-DNS, nicht localhost!)
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
QDRANT_COLLECTION=grundschutz
TOP_K=5
MAX_TOP_K=5
MAX_SOURCE_LINKS=8
SCORE_THRESHOLD=0.0
MAX_TOOL_CALL_ROUNDS=12
STREAMING_ENABLED=false
STREAMING_DOUBLE_PASS=false

# Langflow (deaktiviert für weniger RAM)
LANGFLOW_ENABLED=false
LANGFLOW_BASE_URL=http://langflow:7860
LANGFLOW_FLOW_ID=
LANGFLOW_API_KEY=

# Auto-ingestion
INGEST_DOCLING_JSON_DIR=/data/data_docling_json_ocr
# Beim ersten Start auf true setzen, danach false
INGEST_RECREATE=true
INGEST_BATCH_SIZE=256
INGEST_MAX_BATCH_CHARS=20000

# Pfade (Container-Pfade!)
SYSTEM_PROMPT_PATH=/workspace/system.md
DATA_RAW_DIR=/data/data_raw
GRUNDSCHUTZ_SOURCE_PDF=IT_Grundschutz_Kompendium_Edition2023.pdf
DATA_PREPROCESSED_DIR=/data/data_preprocessed
CITATION_MAP_PATH=./citation_map.json
STARTER_QUESTIONS=Was ist der Unterschied zwischen Prozess- und Systembausteinen?||Welche Schritte umfasst die Basis-Absicherung nach BSI-Standard 200-2?

# Chat history
CHAT_DB_PATH=./.chainlit/chat_history.sqlite3
CHAT_EXPORT_DIR=./.files/chat_exports
```

### Wichtige Hinweise zur .env

1. **Keine Inline-Kommentare nach Werten!**
   ```dotenv
   # FALSCH:
   CHAINLIT_AUTH_SECRET=abc123   # Kommentar wird Teil des Werts!
   
   # RICHTIG:
   # Kommentar auf eigener Zeile
   CHAINLIT_AUTH_SECRET=abc123
   ```

2. **Secret generieren:**
   ```bash
   openssl rand -hex 32
   ```

3. **Unterschiede zu lokaler Entwicklung:**
   | Variable | Lokal | Production |
   |----------|-------|------------|
   | `QDRANT_URL` | `localhost:6333` | `http://qdrant:6333` |
   | `SYSTEM_PROMPT_PATH` | `../../system.md` | `/workspace/system.md` |
   | `DATA_RAW_DIR` | `../../data/data_raw` | `/data/data_raw` |

---

## 6. HTTPS mit Caddy

### 6.1 Caddy installieren

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

### 6.2 Caddyfile konfigurieren

```bash
sudo nano /etc/caddy/Caddyfile
```

```caddyfile
gski.deine-domain.de {
    reverse_proxy localhost:8000
}
```

### 6.3 Caddy starten

```bash
sudo systemctl enable caddy
sudo systemctl restart caddy

# Status prüfen
sudo systemctl status caddy
```

Caddy holt automatisch Let's Encrypt Zertifikate!

### 6.4 Optional: Rate Limiting

```caddyfile
gski.deine-domain.de {
    rate_limit {
        zone dynamic_zone {
            key {remote_host}
            events 100
            window 1m
        }
    }
    reverse_proxy localhost:8000
}
```

---

## 7. GitHub OAuth konfigurieren

1. Gehe zu https://github.com/settings/developers
2. Erstelle neue OAuth App oder bearbeite bestehende
3. Setze **Authorization callback URL** auf:
   ```
   https://gski.deine-domain.de/auth/oauth/github/callback
   ```
4. Client ID und Secret in `.env` eintragen

---

## 8. Container starten

```bash
cd /opt/gski/apps/chainlit

# Alle Container bauen und starten
docker compose up -d --build

# Logs beobachten (Ingest kann 5-20 Min dauern)
docker compose logs -f

# Status prüfen
docker compose ps
```

### Einzelne Services starten/stoppen

```bash
# Nur Chainlit neu starten
docker compose restart chainlit

# Logs eines Services
docker compose logs -f chainlit

# Container-Shell
docker compose exec chainlit /bin/sh
```

---

## 9. Backups einrichten

### 9.1 Backup-Script erstellen

```bash
sudo nano /opt/backup-gski.sh
```

```bash
#!/bin/bash
BACKUP_DIR=/opt/backups/gski
mkdir -p $BACKUP_DIR

# PostgreSQL Backup
docker exec gski-postgres pg_dump -U chainlit chainlit | gzip > $BACKUP_DIR/postgres_$(date +%Y%m%d).sql.gz

# Qdrant Snapshot (optional)
curl -X POST "http://localhost:6333/collections/grundschutz/snapshots"

# Alte Backups löschen (>7 Tage)
find $BACKUP_DIR -mtime +7 -delete

echo "Backup completed: $(date)"
```

```bash
sudo chmod +x /opt/backup-gski.sh
```

### 9.2 Cronjob einrichten (täglich 3 Uhr)

```bash
sudo crontab -e
# Zeile hinzufügen:
0 3 * * * /opt/backup-gski.sh >> /var/log/gski-backup.log 2>&1
```

---

## 10. Monitoring

### 10.1 Einfacher Health-Check

```bash
sudo nano /opt/healthcheck-gski.sh
```

```bash
#!/bin/bash
if ! curl -sf https://gski.deine-domain.de/health > /dev/null 2>&1; then
    echo "GSKI Chainlit DOWN at $(date)" | mail -s "GSKI Alert" admin@example.com
fi
```

```bash
sudo chmod +x /opt/healthcheck-gski.sh

# Alle 5 Minuten prüfen
sudo crontab -e
# Zeile hinzufügen:
*/5 * * * * /opt/healthcheck-gski.sh
```

### 10.2 Container-Logs prüfen

```bash
# Live-Logs aller Services
docker compose logs -f

# Logs eines Services
docker compose logs chainlit | tail -100

# Nach Fehlern suchen
docker compose logs | grep -i error
```

---

## 11. Wartung

### 11.1 Updates einspielen

```bash
cd /opt/gski

# Änderungen vom Repository holen
git fetch origin
git pull origin feature/14-fix-chainlit-resume-citations-pdf-preview

# Container neu bauen
cd apps/chainlit
docker compose down
docker compose up -d --build
```

### 11.2 Qdrant neu indexieren

```bash
cd /opt/gski/apps/chainlit

# In .env: INGEST_RECREATE=true setzen
nano .env

# Ingest ausführen
docker compose up ingest

# Danach INGEST_RECREATE=false setzen
nano .env
```

### 11.3 Datenbank-Reset (Vorsicht!)

```bash
# Alle Daten löschen
docker compose down -v

# Neu starten (erstellt neue Volumes)
docker compose up -d --build
```

---

## 12. Troubleshooting

### Container startet nicht

```bash
docker compose ps
docker compose logs chainlit | tail -50
```

### VPN-Verbindung prüfen

```bash
# Vom Host
curl -s http://10.127.129.0:4000/health

# Aus Container
docker compose exec chainlit python -c "
import urllib.request
try:
    r = urllib.request.urlopen('http://10.127.129.0:4000/health', timeout=5)
    print('OK:', r.read())
except Exception as e:
    print('ERROR:', e)
"
```

### Ports prüfen

```bash
sudo ss -tlnp | grep -E "8000|6333|5432"
```

### Qdrant Vektoranzahl prüfen

```bash
curl -s http://localhost:6333/collections/grundschutz | jq '.result.points_count'
```

---

## 13. Production-Readiness Checkliste

### Erledigt
- [x] HTTPS mit automatischen Let's Encrypt Zertifikaten
- [x] Multi-User Auth (Password + GitHub OAuth)
- [x] Persistente Datenbank (PostgreSQL)
- [x] Separater Admin-User (nicht root)
- [x] Firewall aktiv
- [x] VPN-Tunnel für LiteLLM

### Empfohlen
- [ ] Backups einrichten (Abschnitt 9)
- [ ] Monitoring einrichten (Abschnitt 10)
- [ ] root-SSH deaktivieren (Abschnitt 1.2)
- [ ] Security-Updates aktivieren (Abschnitt 1.4)
- [ ] Log-Rotation konfigurieren

### Optional
- [ ] Rate Limiting (Abschnitt 6.4)
- [ ] Externes Monitoring (Uptime Robot, etc.)
- [ ] Offsite-Backups

---

## Schnellreferenz

### Häufige Befehle

```bash
# Status aller Container
docker compose ps

# Chainlit Logs
docker compose logs -f chainlit

# Chainlit neu starten
docker compose restart chainlit

# Alle Container stoppen
docker compose down

# Alle Container starten
docker compose up -d

# VPN-Status
sudo systemctl status openvpn-client@litellm

# Caddy-Status
sudo systemctl status caddy
```

### Wichtige Pfade

| Pfad | Beschreibung |
|------|--------------|
| `/opt/gski` | Projekt-Root |
| `/opt/gski/apps/chainlit/.env` | Umgebungsvariablen |
| `/opt/gski/apps/chainlit/docker-compose.yml` | Container-Konfiguration |
| `/etc/caddy/Caddyfile` | HTTPS Reverse Proxy |
| `/etc/openvpn/client/litellm.conf` | VPN-Konfiguration |
| `/opt/backups/gski` | Backup-Verzeichnis |

### Wichtige URLs

| URL | Beschreibung |
|-----|--------------|
| `https://gski.deine-domain.de` | Chainlit App |
| `http://localhost:6333/dashboard` | Qdrant Dashboard (nur lokal) |
| `http://localhost:7860` | Langflow (falls aktiviert) |
