# CUPS Print Server — Design

> Backlog #3. A host-installed CUPS print server on blacky that shares the USB-connected
> Brother HL-1110 as a driverless IPP-Everywhere queue, so any LAN client
> (Android/Windows/Apple/Linux) prints with no vendor driver. Reproducible via `setup.sh`.

## Problem

A Brother HL-1110 laser is connected to blacky by USB but usable only as a local printer
on a manually-powered machine — no network sharing. The HL-1110 is a **GDI / host-based**
printer: no PostScript, no PCL, no driverless IPP of its own. We want every device on the
LAN to print to it without installing a vendor driver, and the setup to survive a blacky
rebuild.

## Decision: host install, not Docker

CUPS runs as a **host system service**, not a container. Rationale (decided during
brainstorming):

- **USB:** native access to `/dev/usb/lp0` — no Docker device-cgroup passthrough or
  power-toggle hotplug fragility.
- **mDNS/AirPrint:** blacky's host `avahi-daemon` is already running; host CUPS advertises
  over DNS-SD natively. A containerized CUPS would mean a second avahi responder competing
  with the host one.
- It is a hardware-facing system daemon — the same bucket `setup.sh` already owns (TLP,
  UFW, fstab, systemd units, avahi, mosquitto-clients). Docker's only draw here is
  "everything in compose" consistency, which is outweighed.

Reproducibility is preserved by driving the whole setup from `setup.sh` (apt + a tracked
`cupsd.conf` template + idempotent `lpadmin`).

## Verified current state (blacky, read-only recon)

- Printer live on USB: `lsusb` → `04f9:0054 Brother HL-1110 series`; `/dev/usb/lp0`
  present (usblp loaded, `root:lp`). Serial `C7N798407`.
- CUPS **not installed**. `avahi-daemon` **active**. UFW **active**. Debian **13.4**.
- LAN: blacky `enp0s25` = `192.168.1.222/24` (subnet `192.168.1.0/24`); mDNS already
  allowed in UFW (`5353/udp`). Existing UFW pattern: `ufw allow <port>/tcp comment "…"`
  (LAN-only host, no per-source clause).

## Architecture

### Driver

`printer-driver-brlaser` (open source) supports the HL-1110 (`04f9:0054`). No Brother
binary blob. CUPS rasterizes incoming jobs server-side through brlaser, so the queue can
be presented to clients as a standard **IPP-Everywhere** printer — clients send standard
PWG/URF raster or PDF and CUPS converts. That is what makes a GDI USB printer "driverless"
to every client.

### Components

1. **Packages** (`apt`): `cups`, `printer-driver-brlaser`.
2. **Admin group:** add `yossi` to `lpadmin` (CUPS administrative user).
3. **`cupsd.conf`** — tracked template at `cups/cupsd.conf` (new per-service dir, mirrors
   `mosquitto/config`, `prometheus/config`), copied to `/etc/cups/cupsd.conf` by `setup.sh`:
   - `Listen *:631` + the unix domain socket → LAN devices can submit IPP jobs.
   - `<Location />` → `Order allow,deny` / `Allow @LOCAL` — LAN may print and browse.
   - `<Location /admin>` and `<Location /admin/conf>` → `Allow localhost` only (plus
     `AuthType Default` / `Require user @SYSTEM` on `/admin/conf`) — **the admin/web UI is
     not exposed on the LAN.** Manage via SSH tunnel: `ssh -L 6310:localhost:631 blacky`
     then browse `http://localhost:6310`.
   - `Browsing On` so the shared queue advertises over DNS-SD via the running avahi.
4. **Queue** (idempotent `lpadmin` in `setup.sh`):
   ```
   lpadmin -p HL-1110 \
           -v 'usb://Brother/HL-1110%20series?serial=C7N798407' \
           -m <brlaser PPD> \
           -o printer-is-shared=true -E
   lpadmin -d HL-1110                          # set as default
   lpoptions -p HL-1110 -o media=iso_a4        # A4 default (Israel)
   ```
   The exact PPD model string is resolved at build with `lpinfo -m | grep -i 1110`
   (expected `drv:///brlaser.drv/br1110.ppd`, "Brother HL-1110 series, using brlaser").
   The USB URI is confirmed from the recon (`lpinfo -v` validates it at build).
5. **UFW:** `ufw allow 631/tcp comment "CUPS print server (LAN IPP)"` — mirrors the
   existing 8123/6052 host-network rules. Admin stays localhost-bound at the CUPS layer
   regardless, so only IPP printing endpoints are reachable on the LAN.
6. **Service:** `systemctl enable --now cups`.

### Data flow

Client (phone/laptop) → discovers `HL-1110` via mDNS/DNS-SD on the LAN → submits an
IPP-Everywhere job to blacky:631 → CUPS accepts (Allow @LOCAL) → brlaser rasterizes →
`/dev/usb/lp0` → printer. When the printer is powered off, the queue goes offline and
jobs hold; it resumes when powered on (fits the manual-power workflow — no extra handling).

## Reproducibility

A new idempotent numbered section in `setup.sh`:

- Guard installs so re-runs are safe: skip `apt install` if `dpkg -s cups` succeeds; skip
  `lpadmin` create if `lpstat -p HL-1110` already exists (still re-assert shared/default
  options, which are idempotent).
- Copy the tracked `cups/cupsd.conf` over `/etc/cups/cupsd.conf` and restart cups.
- **Note (documented in the section, like the z2m-config note):** CUPS rewrites
  `/etc/cups/printers.conf` at runtime (queue state) — that file is **not** tracked; the
  queue is recreated by the `lpadmin` lines. Admin-UI changes to `cupsd.conf` won't survive
  a `setup.sh` re-run — the tracked template is the source of truth.

## Files created / modified

- `cups/cupsd.conf` (new) — tracked cupsd config template (LAN print, localhost admin).
- `setup.sh` (modify) — new idempotent section: apt, lpadmin group, cupsd.conf install,
  queue create, A4 default, UFW 631, enable cups.
- `docs/state-of-world.md` (modify) — mark backlog #3 done; note the print server in
  Live Infrastructure.
- `.gitignore` — ignore any CUPS runtime artifacts if a `cups/` working copy appears
  (e.g. `cups/printers.conf`, `cups/*.O` backups) so only the template is tracked.

## Validation (live this session — printer is ON)

1. `dpkg -s cups printer-driver-brlaser` → installed.
2. `lpstat -p -d` → `HL-1110` present, enabled, default.
3. `lpinfo -v` lists the `usb://Brother/HL-1110…serial=C7N798407` device (URI correct).
4. **Test print:** `echo "blacky CUPS test $(date)" | lp -d HL-1110` → page prints
   (physical confirmation from the user).
5. **DNS-SD advertise:** `avahi-browse -rt _ipp._tcp` (and `_ipp-tls`/`_pdl-datastream`)
   shows `HL-1110` on blacky.
6. **Admin lockdown:** `curl -s -o /dev/null -w '%{http_code}' http://192.168.1.222:631/admin`
   from the Mac → `403`/forbidden (LAN admin denied); the same path over the SSH tunnel
   (`localhost:6310/admin`) → reachable.
7. **Cross-client:** user prints a real page from a phone (Android/iOS) and/or the Mac via
   system "Add Printer" → auto-discovered, prints with no driver install.
8. Re-run the `setup.sh` section → no errors, no duplicate queue (idempotency).

## Out of scope (YAGNI)

- Any HA integration (print buttons, "printer off" notifications).
- Scanning / multifunction (HL-1110 is print-only).
- Multiple printers, per-user quotas, accounting.
- HTTPS/TLS on 631 (LAN-only, admin localhost-bound).
- Wake-on-power automation for the printer.
