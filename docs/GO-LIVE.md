# Going live

Plain English, for the owner. It answers one question: what has to happen for
this to run on its own and start booking screener calls. The devops part is
small and covered by `deploy/`. The real work is accounts, DNS, and a list, and
none of it needs you to touch a server.

## What "live" means here

There is no website to turn on. This is a robot that wakes up each weekday
morning, runs the pipeline (find, screen, email, read replies, sync bookings),
and sleeps. "Live" means three things are true:

1. It runs on a small always-on box, on a timer. `deploy/` does this in one
   script.
2. The accounts and keys it needs are filled in.
3. viewlineventures.com is set up to send email that lands in inboxes.

Once those hold, in auto mode it screens with the AI and needs no daily touch
from you. Your job becomes taking the calls that get booked.

## What to sign up for

You chose the paid-API path, so the list builds itself. The stack:

| Job | Tool | Rough cost | Notes |
|---|---|---|---|
| Find profiles | Apollo | ~100-150/mo | People database with search. No LinkedIn scraping. |
| Find and verify emails | Apollo or Findymail | tens/mo | Waterfall; changing it is one config line. |
| The AI screen | Anthropic API | cents per candidate | Pay as you go. Needs a card. |
| Booking calls | Cal.com | free tier | The 10-minute screener link. |
| Send and read replies | your Google Workspace mailbox | already have it | No new vendor. |

Total is low hundreds a month. Payroll is about 268k a month, so the stack is
under 0.1 percent of it. Do not spend a week comparing vendors; pick one of
each and run 300 people through it. `docs/VENDORS.md` has the detail.

## The DNS records (the one blocker on sending)

viewlineventures.com sends through Google Workspace and has SPF, but no DKIM
and no DMARC. Until both exist, mail from it lands in spam or bounces. This is
a 30-minute job for whoever has the domain login (the records point at
Namecheap today).

1. **DKIM.** In the Google Admin console: Apps, Google Workspace, Gmail,
   Authenticate email. Generate a key for viewlineventures.com. Google gives
   you a TXT record (host `google._domainkey`). Paste it at the DNS host, wait
   for it to spread, then click Start authentication.
2. **DMARC.** Add one TXT record at the DNS host:
   - Host: `_dmarc`
   - Value: `v=DMARC1; p=none; rua=mailto:dmarc@viewlineventures.com; fo=1`
   Start with `p=none`. It watches and reports without touching delivery. After
   a couple of clean weeks, tighten to `p=quarantine`, then `p=reject`.

Check both any time:

    python3 -m outbound dns viewlineventures.com

All four of SPF, MX, DKIM and DMARC must say pass before a real send.

## Where it runs, and who sets it up

Any small VM, about 6 USD a month, set up once. The provisioning is one script
(`deploy/setup.sh`); the whole guide is in `deploy/README.md`. The state is a
single SQLite file, so a backup of that file is a backup of everything.

You have not decided who runs that 30-minute setup. Two paths, either works:

- **A contractor or a Sunbird engineer.** Hand them `deploy/README.md` and
  `docs/GO-LIVE.md`. It is a short, well-worn job: clone the repo on a box, run
  the script, paste in the keys. A few hours of an Upwork DevOps person, or an
  afternoon for anyone in-house.
- **Claude across sessions.** A future session can do the config and the deploy
  script, but it cannot create your vendor accounts, enter a card, or edit your
  DNS. Those always need you or a delegate with the logins. So this path still
  needs a person for the account and DNS steps; it just removes the "write the
  setup" part.

Either way, the split is the same: the code and the deploy are handled; the
accounts, the card, and the DNS are yours.

## Go-live order

1. **Decisions (you):** one comp number per seat, and confirm
   viewlineventures.com is the brand. See `docs/DECISIONS.md` and
   `docs/COMP.md`.
2. **Accounts (you):** Apollo, Anthropic (with a card), Cal.com. Put the keys
   somewhere safe to paste in later.
3. **DNS (you or a delegate):** DKIM and DMARC, above. Then wait for them to
   spread, up to a day.
4. **The box (a technical person):** run `deploy/setup.sh`, paste in the keys
   and settings, run `doctor --dns` until it is clean.
5. **Prove it (you):** send yourself a test with
   `outbound send <role> --test-to you@gmail.com --live`, confirm it lands in
   the inbox and the raw headers show SPF, DKIM and DMARC all pass.
6. **Warm up:** two weeks at low volume before pushing toward real numbers. The
   ramp is already in the settings and the code blocks a fast start until you
   attest the mailbox is warmed (`docs/SETUP.md` step 4).
7. **Turn on the timer:** `systemctl enable --now outbound.timer`. It now runs
   itself every weekday.

## What stays hands-off, and what does not

- **Hands-off in auto mode:** finding profiles, screening, drafting the note,
  sending, reading replies, and flagging the bookings that look like a wrong
  fit. The robot does all of it on the timer.
- **Still needs a person:** taking the screener calls, and a glance at the
  weekly report (`outbound report`). Confirming or cancelling a flagged booking
  is one command, or one click if you let `bookings triage --auto` act for you.

That is the whole picture. The code is done; the rest is signing up, one DNS
job, and a 6-dollar box.
