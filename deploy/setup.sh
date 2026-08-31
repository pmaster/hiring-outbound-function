#!/usr/bin/env bash
# One-time provisioning for the outbound recruiting pipeline on a fresh Linux
# box (Ubuntu 24.04 or any distro with Python 3.11+). Run it FROM inside a
# clone of this repo, as root or with sudo:
#
#   sudo bash deploy/setup.sh
#
# It installs the app to /opt/outbound, creates a dedicated user, seeds the
# config files, and installs a systemd timer that runs the pipeline every
# weekday morning. It does NOT put in any keys or send anything: you fill in
# .env and config/settings.toml after, then flip the timer on.
#
# Nothing here is destructive. Re-running it is safe.
set -euo pipefail

APP_DIR=/opt/outbound
APP_USER=outbound
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== outbound deploy =="
echo "source: $SRC_DIR"
echo "target: $APP_DIR"

# 1. Python 3.11+ check. The app has zero pip dependencies, so this is all it
#    needs.
if ! command -v python3 >/dev/null; then
  echo "python3 is not installed. On Ubuntu: apt-get install -y python3"
  exit 1
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
  echo "need Python 3.11+, found $PYV. Install a newer python3 and re-run."
  exit 1
fi
echo "python $PYV: ok"

# 2. Dedicated unprivileged user, so the pipeline does not run as root.
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
  echo "created user $APP_USER"
fi

# 3. Copy the app into place. rsync keeps re-runs fast and leaves .env and the
#    database alone.
mkdir -p "$APP_DIR"
if command -v rsync >/dev/null; then
  rsync -a --delete \
    --exclude '.git' --exclude '.env' --exclude 'data/' \
    "$SRC_DIR"/ "$APP_DIR"/
else
  cp -a "$SRC_DIR"/. "$APP_DIR"/
fi

# 4. Seed the config files if they are not there yet. These are the two files a
#    person fills in.
[ -f "$APP_DIR/.env" ] || cp "$APP_DIR/.env.example" "$APP_DIR/.env"
[ -f "$APP_DIR/config/settings.toml" ] || cp "$APP_DIR/config/settings.example.toml" "$APP_DIR/config/settings.toml"
chmod 600 "$APP_DIR/.env"
mkdir -p "$APP_DIR/data"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod +x "$APP_DIR/scripts/daily.sh" 2>/dev/null || true

# 5. Create the database and load the roles, as the app user.
sudo -u "$APP_USER" python3 -m outbound --config "$APP_DIR/config/settings.toml" init \
  >/dev/null 2>&1 || true
echo "app installed at $APP_DIR"

# 6. Install the systemd timer. It is left DISABLED on purpose: nothing runs
#    until a person has filled in the keys and turned it on.
install -m 644 "$APP_DIR/deploy/outbound.service" /etc/systemd/system/outbound.service
install -m 644 "$APP_DIR/deploy/outbound.timer" /etc/systemd/system/outbound.timer
systemctl daemon-reload
echo "systemd units installed (timer is OFF until you enable it)"

cat <<'NEXT'

== done. what is left, in order ==

  1. Fill in the secrets:
       sudoedit /opt/outbound/.env
     Put in ANTHROPIC_API_KEY, the search/enrichment keys, the Google mailbox
     SMTP and IMAP credentials, and the Cal.com key.

  2. Fill in the settings:
       sudoedit /opt/outbound/config/settings.toml
     Set identity (from address, postal address, unsubscribe URL), the booking
     screener URL, each role's comp and jd_url, and the provider names.

  3. Check it, as the app user:
       sudo -u outbound python3 -m outbound --config /opt/outbound/config/settings.toml doctor --dns
     Fix anything it flags. It will not let a live send start while a check fails.

  4. Send yourself a test, confirm it lands and passes SPF/DKIM/DMARC, then
     attest the warm-up (see docs/SETUP.md step 4 and docs/GO-LIVE.md).

  5. Turn the timer on:
       systemctl enable --now outbound.timer
       systemctl list-timers outbound.timer      # confirm the next run time

  Watch a run by hand any time:
       sudo -u outbound /opt/outbound/scripts/daily.sh          # preview, sends nothing
       journalctl -u outbound.service -n 200 --no-pager         # read the last run

NEXT
