# Deploy kit

Everything needed to run the pipeline on a small always-on Linux box, on a
timer, with no babysitting. For the plain-English "how do we get this live"
picture, read `docs/GO-LIVE.md` first. This file is for whoever does the setup.

## What is here

- `setup.sh`: one-time provisioning. Installs the app to `/opt/outbound`,
  makes a dedicated user, seeds the config files, and installs the timer
  (left off until you turn it on).
- `outbound.service`: one run of the pipeline (`scripts/daily.sh --live`).
- `outbound.timer`: fires the service on weekday mornings, New York time.

## The box

Any small VM works. The app has zero dependencies, so it needs almost nothing:

- 1 shared CPU, 1 GB RAM, 10 GB disk. The smallest tier at any host.
- Ubuntu 24.04 (ships Python 3.12) or any distro with Python 3.11+.
- About 6 USD a month.

The state is one SQLite file at `/opt/outbound/data/`. Back that file up and
you have backed up everything: the candidates, the sends, the bookings.

## Setup, start to finish

    # on your machine, clone the repo, then copy it to the box, or clone on the box
    ssh you@the-box
    git clone <repo-url> outbound && cd outbound
    sudo bash deploy/setup.sh

Then follow the numbered steps it prints: fill in `.env` and
`config/settings.toml`, run `doctor --dns`, send yourself a test, attest the
warm-up, then `systemctl enable --now outbound.timer`.

## Running it by hand

    sudo -u outbound /opt/outbound/scripts/daily.sh           # preview, sends nothing
    sudo -u outbound /opt/outbound/scripts/daily.sh --live    # a real run
    journalctl -u outbound.service -n 200 --no-pager          # read the last timer run
    systemctl list-timers outbound.timer                      # when it runs next

## Updating the code

Pull the new code into the clone and re-run setup. It leaves `.env` and the
database untouched.

    cd ~/outbound && git pull
    sudo bash deploy/setup.sh

## Turning it off

    systemctl disable --now outbound.timer

The data stays. Re-enable any time.
