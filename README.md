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
    python3 -m outbound enrich head-of-operations
    python3 -m outbound verify head-of-operations
    python3 -m outbound queue  head-of-operations
    python3 -m outbound send   head-of-operations --live
    python3 -m outbound bookings sync
    python3 -m outbound bookings triage
    python3 -m outbound report

`outbound report` ends with a "Do next" list. Follow that if you forget the
order.

Everything that is safe to automate is in one script:

    scripts/daily.sh              # dry run
    scripts/daily.sh --live       # sends, up to the daily cap

It does not approve candidates and it does not decide bookings. Both need a
person. It prints what is waiting for you.

## The three rules the code enforces

1. **No detail, no email.** You cannot approve a candidate without writing the
   one specific thing from their profile that goes in line one. Step one of
   every sequence must contain that line. This is the whole edge over a bulk
   campaign, so the code will not let you skip it.
2. **A person approves every send.** Scoring only sorts the queue. Nothing
   reaches the send queue without `outbound review`.
3. **Nothing sends until `doctor` passes.** Placeholder settings, a live brand
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

| Key | Seats | Status |
|---|---|---|
| `head-of-operations` | 1 | live |
| `engineer` | 2 | live |
| `ops-generalist` | 4 | live |
| `controller` | 1 | draft |
| `brand-and-funnel` | 1 | draft |

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

- `docs/SETUP.md` — the domain, the mailboxes, the DNS records, the warm up.
- `docs/RUNBOOK.md` — what to do each day, and who does it.
- `docs/COMPLIANCE.md` — where cold email is lawful and where it is not.
- `docs/OPSEC.md` — what must never share a vector with what.
- `docs/VENDORS.md` — which tools to buy and what they cost.
- `docs/DECISIONS.md` — what is still unanswered and who has to answer it.
