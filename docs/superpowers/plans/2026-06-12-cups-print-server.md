# CUPS Print Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Host-install CUPS on blacky to share the USB Brother HL-1110 as a driverless IPP-Everywhere queue that any LAN client prints to with no vendor driver, reproducible via `setup.sh`.

**Architecture:** CUPS runs as a host system service (not Docker — native USB + uses the existing host avahi for DNS-SD). The `brlaser` open driver handles the GDI HL-1110; CUPS rasterizes server-side and exposes a standard IPP queue. A tracked `cups/cupsd.conf` sets LAN-print / localhost-only-admin access. An idempotent `setup.sh` section installs packages, the config, the queue, and a UFW rule.

**Tech Stack:** Debian 13 host CUPS, `printer-driver-brlaser`, `lpadmin`/`lpoptions`, avahi/DNS-SD, UFW, bash (`setup.sh`).

**Note on testing:** This is host configuration, not Python — there is no pytest suite. Tasks 1-3 produce tracked repo artifacts verified by `bash -n` and inspection. The real verification is the **live Deployment & Validation phase** on blacky (printer is powered on), run after the artifacts are committed. Verifications below are exact shell commands with expected output.

---

## File Structure

- **Create `cups/cupsd.conf`** — the CUPS daemon config template (new per-service dir, mirrors `mosquitto/config/`, `prometheus/config/`). Source of truth for access policy; `setup.sh` installs it to `/etc/cups/cupsd.conf`.
- **Modify `setup.sh`** — new idempotent section `# ── 7c. CUPS print server` (placed after `7b. NAS snapshot cron`, before `8. GitHub SSH key check`): apt install, lpadmin group, install cupsd.conf, create+share queue, A4 default, UFW 631, enable service.
- **Modify `.gitignore`** — track only `cups/cupsd.conf`, ignore any CUPS runtime files that might land in `cups/`.
- **Modify `docs/state-of-world.md`** — mark backlog #3 done; add a Printing row to Live Infrastructure.

Conventions (verified in `setup.sh`): `apt install -y`; helpers `info()`/`warn()`; vars `MAIN_USER="yossi"`, `HA_DIR="/home/${MAIN_USER}/homeassistant"`; UFW already enabled in §6; UFW rule style `ufw allow <port>/tcp comment "…"`.

---

### Task 1: CUPS config template (`cups/cupsd.conf`)

**Files:**
- Create: `cups/cupsd.conf`

- [ ] **Step 1: Create the config**

Create `cups/cupsd.conf` with exactly this content. It is the standard Debian CUPS policy with three deliberate changes: `Listen *:631` (LAN printing), `<Location />` `Allow @LOCAL` (LAN may print/browse), and the `/admin` + `/admin/*` locations restricted to `Allow localhost` (admin UI not exposed on the LAN).

```
# Managed by setup.sh (repo: cups/cupsd.conf) — do not hand-edit on the host.
# LAN devices may print; the admin/web UI is bound to localhost only.
# Manage remotely via: ssh -L 6310:localhost:631 blacky  ->  http://localhost:6310
LogLevel warn
PageLogFormat
MaxLogSize 0
ErrorPolicy retry-job

# Listen on all interfaces for LAN IPP printing, plus the local domain socket.
Listen *:631
Listen /run/cups/cups.sock

# Advertise shared printers over DNS-SD (through the host avahi-daemon).
Browsing On
BrowseLocalProtocols dnssd

DefaultAuthType Basic
WebInterface Yes

# Printing + browsing: allowed from the local network. Admin: localhost only.
<Location />
  Order allow,deny
  Allow @LOCAL
</Location>

<Location /admin>
  Order allow,deny
  Allow localhost
</Location>

<Location /admin/conf>
  AuthType Default
  Require user @SYSTEM
  Order allow,deny
  Allow localhost
</Location>

<Location /admin/log>
  AuthType Default
  Require user @SYSTEM
  Order allow,deny
  Allow localhost
</Location>

# Standard CUPS operation policy (Debian default).
<Policy default>
  JobPrivateAccess default
  JobPrivateValues default
  SubscriptionPrivateAccess default
  SubscriptionPrivateValues default

  <Limit Create-Job Print-Job Print-URI Validate-Job>
    Order deny,allow
  </Limit>

  <Limit Send-Document Send-URI Hold-Job Release-Job Restart-Job Purge-Jobs Set-Job-Attributes Create-Job-Subscription Renew-Subscription Cancel-Subscription Get-Notifications Reprocess-Job Cancel-Current-Job Suspend-Current-Job Resume-Job Cancel-My-Jobs Close-Job CUPS-Move-Job CUPS-Get-Document>
    Require user @OWNER @SYSTEM
    Order deny,allow
  </Limit>

  <Limit CUPS-Add-Modify-Printer CUPS-Delete-Printer CUPS-Add-Modify-Class CUPS-Delete-Class CUPS-Set-Default CUPS-Get-Devices>
    AuthType Default
    Require user @SYSTEM
    Order deny,allow
  </Limit>

  <Limit Pause-Printer Resume-Printer Enable-Printer Disable-Printer Pause-Printer-After-Current-Job Hold-New-Jobs Release-Held-New-Jobs Deactivate-Printer Activate-Printer Restart-Printer Shutdown-Printer Startup-Printer Promote-Job Schedule-Job-After Cancel-Jobs CUPS-Accept-Jobs CUPS-Reject-Jobs>
    AuthType Default
    Require user @SYSTEM
    Order deny,allow
  </Limit>

  <Limit Cancel-Job CUPS-Authenticate-Job>
    Require user @OWNER @SYSTEM
    Order deny,allow
  </Limit>

  <Limit All>
    Order deny,allow
  </Limit>
</Policy>
```

- [ ] **Step 2: Sanity-check the file exists and has the three key directives**

Run:
```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
grep -E "Listen \*:631|Allow @LOCAL|Allow localhost" cups/cupsd.conf
```
Expected: prints the `Listen *:631`, `Allow @LOCAL`, and (twice+) `Allow localhost` lines.

- [ ] **Step 3: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add cups/cupsd.conf
git commit -m "feat(cups): cupsd.conf template — LAN print, localhost-only admin"
```

---

### Task 2: `setup.sh` CUPS section

**Files:**
- Modify: `setup.sh` (insert a new section immediately before `# ── 8. GitHub SSH key check ─────`)

- [ ] **Step 1: Insert the section**

Use the Read tool to locate `# ── 8. GitHub SSH key check` in `setup.sh`, then insert this block **immediately before** that line. (`MAIN_USER` and `HA_DIR` are defined near the top; UFW was enabled in §6; `info`/`warn` exist.)

```bash
# ── 7c. CUPS print server ─────────────────────────────────────────────────────
# Host-installed CUPS sharing the USB Brother HL-1110 as a driverless IPP-Everywhere
# queue. Driver: brlaser (open). Admin UI bound to localhost; LAN may print only.
# The tracked cups/cupsd.conf is the source of truth; printers.conf (queue state) is
# regenerated by the lpadmin lines below and is NOT tracked.
info "Setting up CUPS print server (Brother HL-1110)..."

if ! dpkg -s cups >/dev/null 2>&1; then
    apt install -y cups printer-driver-brlaser
fi

# Administrative rights for the main user (CUPS admin group).
usermod -aG lpadmin "$MAIN_USER" || true

# Access policy from the tracked template (LAN print, localhost-only admin).
if [[ -f "${HA_DIR}/cups/cupsd.conf" ]]; then
    install -m 0640 -o root -g lp "${HA_DIR}/cups/cupsd.conf" /etc/cups/cupsd.conf
else
    warn "Missing ${HA_DIR}/cups/cupsd.conf — leaving CUPS default config."
fi

systemctl enable cups
systemctl restart cups
sleep 2

# Resolve the brlaser PPD for the HL-1110, then create/assert the shared queue.
HL1110_URI="usb://Brother/HL-1110%20series?serial=C7N798407"
HL1110_PPD="$(lpinfo -m 2>/dev/null | grep -iE 'br1110|HL-1110' | head -n1 | awk '{print $1}')"
HL1110_PPD="${HL1110_PPD:-drv:///brlaser.drv/br1110.ppd}"
lpadmin -p HL-1110 -v "$HL1110_URI" -m "$HL1110_PPD" -o printer-is-shared=true -E
lpadmin -d HL-1110
lpoptions -p HL-1110 -o media=iso_a4 >/dev/null

# Firewall: allow IPP on the LAN (admin stays localhost-bound at the CUPS layer).
ufw allow 631/tcp comment "CUPS print server (LAN IPP)"

info "CUPS ready — HL-1110 shared (driverless IPP). Admin via: ssh -L 6310:localhost:631 blacky -> http://localhost:6310"
```

- [ ] **Step 2: Syntax-check**

Run:
```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
bash -n setup.sh && echo "syntax OK"
```
Expected: `syntax OK`.

- [ ] **Step 3: Verify placement + key commands present**

Run:
```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
grep -n "7c. CUPS print server\|lpadmin -p HL-1110\|ufw allow 631" setup.sh
```
Expected: the section header, the `lpadmin -p HL-1110` line, and the `ufw allow 631/tcp` line all appear, located before the `# ── 8. GitHub SSH key check` header.

- [ ] **Step 4: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add setup.sh
git commit -m "feat(cups): setup.sh section — install, share HL-1110, UFW 631"
```

---

### Task 3: `.gitignore` + state-of-world doc

**Files:**
- Modify: `.gitignore`
- Modify: `docs/state-of-world.md`

- [ ] **Step 1: Track only the template, ignore CUPS runtime files**

Append to `.gitignore` (at the end):

```
# ── CUPS ─────────────────────────────────────────────────────────────────────
# Track only the cupsd.conf template; ignore any runtime/state files that might
# land in cups/ (printers.conf etc. are regenerated on the host by lpadmin).
cups/*
!cups/cupsd.conf
```

- [ ] **Step 2: Confirm the template is still tracked**

Run:
```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git check-ignore cups/cupsd.conf; echo "exit=$?"
```
Expected: no path printed and `exit=1` (meaning `cups/cupsd.conf` is NOT ignored — the negation works).

- [ ] **Step 3: Update the backlog item in `docs/state-of-world.md`**

Find the backlog line `3. **CUPS print server** — Brother USB laser → LAN, hosted on `blacky`.` in section "## 7. Future Automation Backlog" and replace it with:

```
3. ✅ **CUPS print server** *(done — host CUPS + brlaser on blacky; config `cups/cupsd.conf`,
   queue + UFW provisioned by `setup.sh`)* — Brother HL-1110 (USB, GDI) shared as a
   driverless IPP-Everywhere queue over the existing avahi/DNS-SD; Android/Windows/Apple/Linux
   print with no client driver. Admin UI bound to localhost (manage via
   `ssh -L 6310:localhost:631 blacky`); LAN may print only. A4 default. Printer is manually
   powered — the queue holds when it's off and resumes when on.
```

- [ ] **Step 4: Add a Printing row to the Live Infrastructure table**

In `docs/state-of-world.md` section "## 2. Live Infrastructure", in the "Integrations & devices (live)" table (the one whose rows look like `| Messaging | Telegram bot | |`), add this row immediately after the `| Zigbee | ... |` row:

```
| Printing | CUPS — Brother HL-1110 (USB, brlaser) | shared driverless IPP-Everywhere; LAN print, localhost admin |
```

- [ ] **Step 5: Verify both doc edits**

Run:
```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
grep -n "3. ✅ \*\*CUPS\|Printing | CUPS" docs/state-of-world.md
```
Expected: both the backlog `3. ✅ **CUPS` line and the `Printing | CUPS` table row appear.

- [ ] **Step 6: Commit**

```bash
cd /Users/yossi_solomon/dev/HomeAutomationSetup
git add .gitignore docs/state-of-world.md
git commit -m "docs(cups): gitignore runtime, mark #3 done, list print server"
```

---

## Deployment & Validation (live on blacky — controller-run, printer is ON)

These steps make real system changes (apt, `/etc/cups`, lpadmin, UFW, service enable) on the
live server and require a physical print confirmation. Run after Tasks 1-3 are committed and
the branch is merged + pulled on blacky (or run against the working tree already on blacky).
Each step lists the exact command and expected result.

- [ ] **D1: Get the artifacts onto blacky** (after merge+push, or copy the working tree):
  ```bash
  ssh blacky 'cd /home/yossi/homeassistant && git pull --ff-only && ls cups/cupsd.conf'
  ```
  Expected: `cups/cupsd.conf` present.

- [ ] **D2: Install packages:**
  ```bash
  ssh blacky 'sudo apt install -y cups printer-driver-brlaser && dpkg -s cups printer-driver-brlaser | grep -E "^Package|^Status"'
  ```
  Expected: both packages `Status: install ok installed`.

- [ ] **D3: Install access config + enable service:**
  ```bash
  ssh blacky 'sudo install -m 0640 -o root -g lp /home/yossi/homeassistant/cups/cupsd.conf /etc/cups/cupsd.conf && sudo systemctl enable --now cups && sudo systemctl restart cups && sleep 2 && systemctl is-active cups'
  ```
  Expected: `active`.

- [ ] **D4: Confirm the device URI + PPD resolve:**
  ```bash
  ssh blacky 'lpinfo -v | grep -i brother; echo "---"; lpinfo -m | grep -iE "br1110|HL-1110"'
  ```
  Expected: a `usb://Brother/HL-1110%20series?serial=C7N798407` device line, and a brlaser PPD line (e.g. `drv:///brlaser.drv/br1110.ppd Brother HL-1110 series, using brlaser`).

- [ ] **D5: Create + share the queue, set A4 default:**
  ```bash
  ssh blacky 'sudo usermod -aG lpadmin yossi; PPD=$(lpinfo -m | grep -iE "br1110|HL-1110" | head -n1 | awk "{print \$1}"); PPD=${PPD:-drv:///brlaser.drv/br1110.ppd}; sudo lpadmin -p HL-1110 -v "usb://Brother/HL-1110%20series?serial=C7N798407" -m "$PPD" -o printer-is-shared=true -E && sudo lpadmin -d HL-1110 && sudo lpoptions -p HL-1110 -o media=iso_a4 && lpstat -p -d'
  ```
  Expected: `printer HL-1110 is idle…`, `enabled`, and `system default destination: HL-1110`.

- [ ] **D6: Open the firewall for LAN IPP:**
  ```bash
  ssh blacky 'sudo ufw allow 631/tcp comment "CUPS print server (LAN IPP)" && sudo ufw status | grep 631'
  ```
  Expected: a `631/tcp ALLOW` rule.

- [ ] **D7: TEST PRINT (physical):**
  ```bash
  ssh blacky 'echo "blacky CUPS test page $(date)" | lp -d HL-1110 && sleep 3 && lpstat -W completed -o HL-1110'
  ```
  Expected: a job id queued, and a **printed page** comes out of the HL-1110. (Ask the user to confirm the page printed.)

- [ ] **D8: DNS-SD advertisement (generic discovery):**
  ```bash
  ssh blacky 'avahi-browse -rt _ipp._tcp 2>/dev/null | grep -A3 -i HL-1110 | head'
  ```
  Expected: `HL-1110` advertised on blacky over `_ipp._tcp` (this is what Android/Windows/Apple discover).

- [ ] **D9: Admin lockdown check (LAN denied, tunnel allowed):**
  ```bash
  # From the Mac — LAN admin must be forbidden:
  curl -s -o /dev/null -w 'LAN /admin -> %{http_code}\n' http://192.168.1.222:631/admin
  # Over an SSH tunnel — admin reachable:
  ssh -fNT -L 6310:localhost:631 blacky && curl -s -o /dev/null -w 'tunnel /admin -> %{http_code}\n' http://localhost:6310/admin; pkill -f '6310:localhost:631'
  ```
  Expected: LAN `/admin` → `403`; tunnel `/admin` → `200` (or `401` auth-prompt, also fine — both mean reachable, vs `403` forbidden on the LAN).

- [ ] **D10: Cross-client real print (user, manual):**
  Ask the user to add the printer from a phone (Android default print / iOS) and/or the Mac
  ("Add Printer" → it auto-appears via Bonjour/mDNS) and print a page — confirming no driver
  install was needed.

- [ ] **D11: Idempotency:** re-run D2-D6 once more → no errors, `lpstat -p` still shows a
  single `HL-1110` (no duplicate queue), UFW reports the rule already exists.

---

## Self-Review notes

- **Spec coverage:** host-install + brlaser → Task 2 / D2,D5; cupsd.conf access model → Task 1 / D3,D9; shared driverless IPP + DNS-SD → Task 2 (`printer-is-shared`, `Browsing On`) / D8,D10; UFW 631 → Task 2 / D6; A4 default → Task 2 / D5; reproducible setup.sh + idempotency → Task 2 / D11; printers.conf-not-tracked note → Task 2 comment + Task 3 `.gitignore`; docs → Task 3. All spec sections mapped.
- **Consistency:** queue name `HL-1110`, URI `usb://Brother/HL-1110%20series?serial=C7N798407`, and PPD-resolution one-liner are identical in the `setup.sh` section (Task 2) and the live steps (D5).
- **YAGNI:** no HA integration, no TLS, no scanning, no multi-printer — all out of scope per spec.
- **Note:** Tasks 1-3 are repo artifacts (subagent-safe). The Deployment phase (D1-D11) makes live system changes + needs physical confirmation → controller-run with the user, not a subagent.
```
