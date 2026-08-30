# Open decisions

What is not settled, who settles it, and what it blocks. Written 2026-08-30
while building the pipeline. Everything here was hit during the build and
worked around, so the code runs. None of it is a code problem.

Ranked by what unblocks the most.

## 1. Comp numbers. Peter. Blocks every live send.

`hiring-pack.md` still has `[$X]` for every role. Step one of every sequence
puts the comp number in the email, because a senior operator will not answer a
blind approach. `outbound doctor` refuses to send while it is unset.

What to do: put a number, or a band, in `config/settings.toml`.

    [role_overrides.head-of-operations]
    comp = "$14,000 to $18,000 a month"

The demo file has invented numbers so the pipeline runs. They are not
proposals. Replace them.

Also unsettled: is the Head of Operations seat a full time contractor or
fractional? `hiring-pack.md` asks and nobody answered.

## 2. The sending domain and mailboxes. Peter or Lulu. Blocks every live send.

Nothing exists yet. The domain has to be registered, hosted separately, and
warmed for ten days. That is the long pole, so start it before building a
list. Steps in `SETUP.md`, reasoning in `OPSEC.md`.

The card matters. Do not use a card linked to the live brands.

## 3. Which enrichment vendor. Peter. Blocks enrichment only.

The sourcing doc says Peter is researching this and names Apify, Instantly and
"Rocket something". Adapters exist for Apify, Apollo, RocketReach and
Findymail, and for MillionVerifier and NeverBounce to verify. Costs and a
recommendation are in `VENDORS.md`.

Until one is chosen, `providers.enrich = "dryrun"` and nothing is bought.

At 300 people this decision is worth about fifty dollars, so do not spend a
week on it.

## 4. The screener booking page. Whoever owns the calendar. Blocks bookings.

No booking URL exists. Ten minutes, not fifteen. Put the four role questions on
the form as required questions:

    python3 -m outbound questions head-of-operations

Then set `booking.screener_url`. Adapters exist for Cal.com and Calendly.

## 5. Job description pages. Peter. Blocks step one of every sequence.

Every email links to a job description. The pages are now written and built:

    python3 -m outbound pages

That writes `site/` with a careers index, one page per live role, and an
unsubscribe page. Self contained HTML, no external requests, works in light
and dark. The text is in `content/jd/*.md`, drawn from `hiring-pack.md`
Part 3 and `employee-pitch.md` Version 1.

Two things left, both Peter's:

1. Read them. They say "we have hired badly for this seat, four attempts in
   two years" and "we have no financial reporting worth the name". That is
   deliberate and it is the most persuasive part of the document to the only
   kind of candidate we want. If you soften it, say so; do not soften it by
   accident.
2. Host `site/` on the recruiting domain, then set each `jd_url` in
   `config/settings.toml`.

The pages are T1 only: a small trading firm in alternative assets, around
fifty people. No casino, no client model, no fund flow. A test enforces this
on both the pages and the emails, so an edit that crosses the line fails the
build rather than reaching a candidate.

The unsubscribe page's form action is a placeholder. Point it at anything that
records an address, then load the results with
`outbound suppress --from-file`.

## 6. The platform cause test. Lulu. Blocks the inbound half, not this machine.

The LinkedIn and Indeed problems have two candidate causes and nobody has
tested which one it is.

- Identity contamination: the platforms match Peter, Emi or the card. A clean
  entity fixes it.
- Content and behaviour: the platforms match the postings themselves. A new
  entity gets burned the same way and you paid for it.

The test: post one normal full time role from Sunbird Systems LLC, from a
browser profile and IP Peter has never used, paid with an unlinked card. Wait
14 days. Survives means cause one. Removed means cause two.

Cost of the test: one job posting. Cost of skipping it: a burned entity and
six weeks. This gates the entity spend, so run it first.

Correct one fact while you are there. Sunbird Systems LLC exists, EIN
33-2384783. "We are not incorporated" is true of Viewline Ventures only.

## 7. The posting entity question. Gary Kondler, then Peter.

The sourcing doc floats using "a third party's incorporated entity we just use
for posting". That is the nominee route. `brand-opsec-sop.md` marks it
[MISREP-RISK] and routes it to Kondler. Ask before, not after. Platform
verification asks for owner identity, so the version that survives is an entity
genuinely owned by someone genuinely in the operation.

## 8. The plaintext password in the sourcing doc. Whoever owns Dstribute. Now.

The Dstribute section of the sourcing Google Doc contains a shared default
password for three named people. Delete it from the doc, move the credentials
to a password manager, and force a reset. It is not used by this repo and it
is not stored here.

## 9. Lulu's job board list. Lulu.

Referenced in the sourcing doc, written down nowhere. It is the channel for
the volume seats and for every country this machine will not email.

## 10. Whether the volume seats belong in outbound at all. Peter.

The outbound SOP argues there are three hiring problems and cold email fits
only one: the senior, rare seats. The nineteen US volume seats are blocked by
platform access, not by channel count, and the offshore seats are blocked by
consent law.

The `ops-generalist` role in this repo is the middle case: four seats, a
bigger list, sent by a coordinator rather than Peter. It is configured as
live. If you decide outbound is for senior seats only, set
`status = "draft"` in `config/roles/ops-generalist.toml` and the machine stops
sending it. One word.

## 11. The book-then-cancel step. Peter, already decided, noted here.

The sourcing doc describes letting everyone book, then re-checking the profile
and cancelling the ones that are not a fit, with an apology. The outbound SOP
argues against it: it makes angry people, and angry people write the public
complaints that plausibly cause the platform problems above.

Peter asked for the doc version, so it is built. Both halves are here:

- The booking form takes four required questions, which is the gate that
  avoids most cancellations. Use it.
- `outbound bookings triage` re-checks every booker and suggests confirm or
  cancel. Cancelling always sends the apology and warns inside 12 hours.

The default is a person deciding one at a time. `--auto` acts on every
suggestion. Do not use `--auto` until you have watched the suggestions be
right for a week.

## What was assumed to keep building

Where a fact was missing, the code marks it rather than inventing it.

| Assumption | Where | How to change it |
|---|---|---|
| US only sending | `compliance.allow_countries` | `COMPLIANCE.md`, and take Canada and the EU to counsel first |
| Comp goes in email one | `role.comp_in_email = true` | Set false in the role file if you disagree |
| Three emails, days 0, 4 and 8 | `sending.step_gap_days` | Change in settings |
| 18 a day per mailbox, two mailboxes | `sending.*` | Change in settings |
| Head of Operations and Engineer are the seats that matter | role status | Set `status = "live"` on `controller` when its comp lands |
| Controller and Brand and Funnel are drafts | role files | The priorities doc argues Controller before Engineer. Peter's call. |
