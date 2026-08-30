# Outbound recruiting

Find candidates for the open seats, write to them, and screen the ones who
book. Built for Sunbird from the sourcing doc and the outbound SOP.

The flow, end to end:

    find profiles -> score against the role ICP -> a person reads each one
      -> find the work email -> verify it -> send a three step sequence with
      the job description and a ten minute screener link -> read bookings back
      -> re-check the person -> confirm or cancel with an apology

Python 3.11 or later. No dependencies. Nothing to install.

## Run it now, offline

    python3 -m outbound demo

This runs the whole funnel against sample data with no API keys and no
network. It writes the rendered emails to `data/demo/outbox/`. Nothing is
sent. Read the output, then read one of the `.eml` files.

## Set it up for real

    python3 -m outbound init          # creates config/settings.toml and .env
    # edit config/settings.toml: identity, screener_url, and the comp numbers
    python3 -m outbound doctor        # tells you what is still missing
    python3 -m outbound dns           # checks SPF, DKIM, DMARC and MX
    python3 -m outbound pages         # builds site/ : careers page, JDs, unsubscribe

`doctor` refuses to pass while anything says CHANGEME, while the sending
domain is a live brand, or while a role that puts comp in the email has no
comp. Fix what it names, then run it again.

## The daily loop

    python3 -m outbound search head-of-operations       # print the queries
    # build the list in the browser, save as CSV
    python3 -m outbound import head-of-operations list.csv
    python3 -m outbound score  head-of-operations
    python3 -m outbound review head-of-operations       # read each profile
    python3 -m outbound review head-of-operations --approve 41 --note "..."
    # or work through them offline in a spreadsheet:
    python3 -m outbound review head-of-operations --export review.csv
    python3 -m outbound review head-of-operations --import-file review.csv
    python3 -m outbound audit  head-of-operations       # is this list ready
    python3 -m outbound enrich head-of-operations
    python3 -m outbound verify head-of-operations
    python3 -m outbound queue  head-of-operations
    python3 -m outbound send   head-of-operations --test-to you@gmail.com --live
    python3 -m outbound send   head-of-operations --live
    python3 -m outbound replies sync                    # replies and bounces
    python3 -m outbound inbox                           # read what they said
    python3 -m outbound bookings sync
    python3 -m outbound bookings triage
    python3 -m outbound export --format ats            # hand them to the ATS
    python3 -m outbound report

`outbound report` ends with a "Do next" list. Follow that if you forget the
order.

Everything that is safe to automate is in one script:

    scripts/daily.sh              # preview: writes the outbox, changes nothing
    scripts/daily.sh --live       # sends, up to the daily cap

It does not approve candidates and it does not decide bookings. Both need a
person. It prints what is waiting for you.

## Replies and bounces

`outbound replies sync` reads the sending mailbox over IMAP and moves anyone
who answered out of the sequence. It also reads hard bounces off the delivery
reports and suppresses those addresses.

This matters more than it sounds. Sending "I am closing this search" to
someone who replied four days ago is the one mistake that turns a good
approach into a bad story.

If the scan misses something, or a reply arrives by another route:

    python3 -m outbound replies mark someone@company.com
    python3 -m outbound replies mark someone@company.com --kind unsubscribed

Where it reads from is configurable. `providers.replies = "imap"` reads the
sending mailbox, which is right when the mailboxes are yours. Set it to
`"instantly"` when the sequencer owns the sending, because that is where the
replies land. Either way this database is what the report and the stage logic
read.

## The four rules the code enforces

1. **No detail, no email.** You cannot approve a candidate without writing the
   one specific thing from their profile that goes in line one. Step one of
   every sequence must contain that line. This is the whole edge over a bulk
   campaign, so the code will not let you skip it.
2. **A person approves every send.** Scoring only sorts the queue. Nothing
   reaches the send queue without `outbound review`.
3. **The daily cap is per sending domain, not per role.** The mailboxes are
   shared, so one role's sends limit another's. Three live roles cannot each
   send eighteen a day out of two mailboxes.
4. **Nothing sends until `doctor` passes.** Placeholder settings, a live brand
   domain, an unset comp number or a draft role all stop a live send.

## Layout

| Path | What it holds |
|---|---|
| `config/settings.example.toml` | Every setting, with comments. Copy to `settings.toml`. |
| `config/roles/*.toml` | One file per seat: the ICP, the scoring signals, the searches, the screener questions. |
| `templates/<role>/step-N.md` | The three emails. `Subject:` line, then the body. |
| `templates/shared/` | The cancellation apology and the confirmation note. |
| `outbound/` | The code. One module per stage. |
| `content/jd/*.md` | The job description text, one per live role. |
| `site/` | The built careers pages. Generated. Upload it to the recruiting domain. |
| `sample/` | Sample profiles, sample bookings, and demo settings. |
| `docs/` | Setup, runbook, vendors, compliance, opsec, open decisions. |
| `data/` | The database and the outbox. Gitignored. It holds real people. |

## Roles shipped

Nine seats, built from the source documents. `docs/SOURCE-BRIEF.md` traces
every criterion to the file it came from.

| Key | Seats | Status | Why |
|---|---|---|---|
| `head-of-operations` | 1 | live | Sought 1.5 to 2 years, four failed attempts. Also covers Director of Ops and VP Ops, because which title is hired is undecided. |
| `engineer` | 2 | live | About twenty initiatives on the seat and one person in it. |
| `ops-generalist` | 4 | live | Four departments with no head. |
| `chief-of-staff` | 1 | draft | One of the three Peter calls most important. Comp conflicts with itself in the source. |
| `quant-program-manager` | 1 | draft | The third of those three. |
| `fulfillment-specialist` | 15 | draft | Called the number one business priority. Metro locked, and the live gate is a test people are failing. Read the file before making it live. |
| `business-systems-lead` | 1 | draft | Top five priority. No comp in any source document. |
| `controller` | 1 | draft | The heaviest vacancy on the issues register. |
| `brand-and-funnel` | 1 | draft | The largest block of Peter's time a single hire removes. |

Draft roles load and score but refuse to send. Set `status = "live"` in the
role file once the comp and the job description are settled.

## Changing a role

Everything about a seat is in one TOML file. Edit `config/roles/<key>.toml`:

- `[icp]` sets the search filters and the titles to exclude.
- `[[signal]]` blocks set the score. Weights are relative and are normalised,
  so you can add a signal without rebalancing the others. A negative weight is
  a penalty, not a reject.
- `[[disqualifier]]` blocks are hard rejects.
- `[booking] questions` are the screener form questions.
- `[[search]]` blocks become the queries `outbound search` prints.

Then re-score what you already have:

    python3 -m outbound score head-of-operations --restage

## Comp numbers

Comp does not live in the role files, because those are committed. Put it in
`config/settings.toml`, which is not:

    [role_overrides.head-of-operations]
    comp   = "$14,000 to $18,000 a month"
    jd_url = "https://.../roles/head-of-operations"

## Tests

    python3 -m unittest discover -s tests -v

## Read next

- `docs/FIRST-WEEK.md` — **start here.** An ordered two week plan.
- `docs/SETUP.md` — the domain, the mailboxes, the DNS records, the warm up.
- `docs/RUNBOOK.md` — what to do each day, and who does it.
- `docs/COMPLIANCE.md` — where cold email is lawful and where it is not.
- `docs/OPSEC.md` — what must never share a vector with what.
- `docs/COMP.md` — the comp band per seat, where it came from, and how sure I am.
- `docs/VENDORS.md` — which tools to buy, and what to check before buying.
- `docs/VENDOR-APIS.md` — every vendor endpoint, verified against live docs.
- `docs/DECISIONS.md` — what is still unanswered and who has to answer it.
- `docs/ROLE-INTAKE.md` — what is needed to define a seat, and where each answer goes.
- `docs/ARCHITECTURE.md` — how the code fits together, for whoever maintains it.
