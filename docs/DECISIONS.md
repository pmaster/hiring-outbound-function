# Open decisions

What is not settled, who settles it, and what it blocks.

Written 2026-08-30 while building the pipeline, then rewritten after a
recursive crawl of 40 Google Drive files. The crawl output, with a fileId on
every claim, is `SOURCE-BRIEF.md`. Read that when an answer here is not enough.

Everything here was hit during the build and worked around, so the code runs.
None of it is a code problem.

---

## The three that block every live send

### 1. Comp numbers. Peter.

Step one of every sequence puts the comp number in the email, because a senior
operator will not answer a blind approach, and because LinkedIn increasingly
requires a stated range on postings. `outbound doctor` refuses to send while it
is unset.

The crawl found comp for most seats, but it does not agree with itself:

| Seat | What the documents say |
|---|---|
| Director of Operations | $130k-$180k plus bonus, **and** $130k-$160k, **and** $135k-$175k base plus 0.5%-1.5% equity. Three figures, one document. |
| Chief of Staff | $105k-$145k base plus 0.25%-0.75% equity, **and** $100k-$140k. Same document. |
| Quant Program Manager | $90k-$125k base plus performance bonuses. Single figure. |
| Fulfillment Specialist / QIS | Fourteen different bands across five public titles and seven cities, plus "$90k+/year" and "$20-$35/hour" elsewhere. |
| Quantitative Trader | "$90k+/year" **and** "$90k to $160k". Payroll shows about $6.2k a month each. |
| Business Systems Lead | Blank in every tab of the posting sheet. |
| Engineer | No band. Incumbent at about $8.6k a month. |

Pick one number per seat and put it in `config/settings.toml`:

    [role_overrides.head-of-operations]
    comp = "$135,000 to $175,000 with performance upside"

The demo file has invented numbers so the pipeline runs. They are not
proposals. Replace them.

### 2. The sending domain. Peter. Lock it for 12 months.

Nothing is registered or warmed. Warm up is ten days, so this is the long pole.

There is a real disagreement in the sources and the code no longer picks a
side:

- Peter's own scoping doc designates **viewlineventures.com** as the FTE
  hiring domain, used exclusively for full-time hiring. It already sends job
  notifications from `team@`.
- The outbound SOP says do not send from it: one complaint cluster blocklists
  the domain and takes normal business email with it.
- A third doc lists replacing the Viewline brand entirely as an open item, the
  new recruiting organisation is unnamed, and the three-entity split is
  mid-selection.

Building sending reputation on a domain about to be retired wastes the warm
up. So this is one decision, made once, for at least a year.

What the code does now: **hard blocks** cornerstonegigs.com (client and gig
worker domain, and the name fails bank compliance checks), sunrunlabs.com
(internal corporate identity), and the free mail providers. It **warns** on
viewlineventures.com and sunbirdsystems.com and names the tradeoff, because
those are a judgment call, not a rule.

### 3. Job description pages. Peter.

The pages are written and built:

    python3 -m outbound pages

That writes `site/` with a careers index, one page per live role, and an
unsubscribe page. Two things left: read them, and host them on whichever
domain answers question 2.

They say "we have hired badly for this seat, four attempts in two years" and
"we have no financial reporting worth the name". That is deliberate and it is
the most persuasive part of the document to the only candidate worth having.
If you soften it, do it on purpose.

---

## The ones that change what gets built

### 4. Which roles, in what order, at what headcount. Peter.

Three separate priority lists exist and none matches the others. About thirty
distinct seats are named across the crawl.

- **Sunbird Memos:** the three most important are Director of Ops, Chief of
  Staff and Quant Program Manager, which Peter calls "mostly pretty
  overlapping/interchangeable".
- **FTE Hiring Notes:** Fulfillment Specialist / QIS is the "#1 business
  priority", 10 to 15 hires by end of year, 3 immediately. Business Systems
  Lead is top five.
- **The rocks list:** hire the engineer and replace the incumbent, hire
  finance and ops, build client support, hire Canadian quants.

Eight roles are configured. Three are live and five are drafts that score but
refuse to send. Needed: a ranked list of three to five, with headcount and a
start date. Everything else can stay a draft.

### 5. Booking link, or assessment first. Peter.

The brief you gave says the first email carries a job description and a
ten minute screener booking link. Your own memo says you want to "just go off
great assessments and push volume and quality through those funnels" and that
you do not want to interview or read resumes.

Those are different funnels with different economics and different build
orders. The machine is built for the booking link. Pointing it at an
assessment link instead is a one line change in the templates, but the
assessments mostly do not exist yet (question 8).

### 6. The booking link itself. Peter, with engineering.

No candidate scheduling tool exists. Google Calendar runs the client info
sessions, Calendly appears once inside a job description, and there is a memo
proposing to **build** a Calendly competitor with a full feature list.

Buy Calendly or Cal.com now, or wait for the internal build. Adapters for both
are written. Ten minutes, not fifteen, and put the four role questions on the
form as required questions:

    python3 -m outbound questions head-of-operations

### 7. What the email discloses. Peter.

The opsec rule is to stay coy: "we don't want to inspire or aid competition,
we don't want to alert or end up on casinos' radars".

The client side has a full disclosure ladder, generic before the NDA and
complete after. There is no equivalent ladder for candidates.

What the code does now: the emails and the public pages use the T1 line from
`employee-pitch.md`, "a small trading firm in alternative assets, around fifty
people". A test enforces that nothing crosses that line, checking for the
domain, the platforms, the processors and the model. Note one live tension:
the Q1 posting guidance avoids the word "trading" entirely for LinkedIn
postings, while the August pitch document approves "trading firm in
alternative assets" for candidate-facing use. Email is not a LinkedIn posting,
so the newer line is used. Change `T1_BANNED` in the tests if you disagree.

### 8. Do the assessments exist. Peter, with Wency.

Mostly no. CCAT is live and is the current bottleneck: "not enough qualified
applicants passing the cogap test". Everything else, the KYC document test,
typing, the car rental research task, the consulting case, the SOP writing
task, is on a to-do list. There is no Business Systems Lead assessment at all;
Peter takes those interviews himself as discovery.

If question 5 resolves to assessment-first, the build cannot start until these
exist.

### 9. Who owns this day to day. Peter.

Six candidates appear in the documents: Miriam is told to start outreach, Max
may consult on the hiring system, Emi runs screening, Callum is redesigning
scripts, the Chief of Staff scorecard includes FTE recruiting velocity, and
agencies are being priced. One named owner is needed.

The real constraint on this function is not cost. The tool stack is under 0.1
percent of payroll. It is that this needs a person every working day.

### 10. W2 or 1099. Peter, with finance.

Every row in the posting sheet is 1099, long-term contract, or contract-to-hire,
despite the file being titled "FTE Job Posting". The notes record this as
unresolved.

It matters beyond the offer letter: LinkedIn scrutinises 1099 contract roles
harder because they overlap with gig postings and "be your own boss" schemes.
Suggested reframes are already on file.

### 11. Onshore or offshore. Peter.

Asked verbatim in the source and never answered: "do we go onshore or offshore
for these remote positions? do we focus on talent or experience? do we prefer
seniority or not?"

This decides the geography filter for every remote role. The machine is US
only, because that is where cold email is lawful and advisable. Offshore
sourcing goes through agencies and local boards either way, so this question
changes the role configs, not the machine.

### 12. Which ops leadership title is actually hired. Peter.

COO, VP Ops, or Director of Ops. The source lays out all three, says "you
likely need one of the following three", and does not choose. One tab commits
to VP Ops; the market map calls Director of Ops the sweet spot and says to
exclude VP and above on the first pass.

`head-of-operations` currently searches all three and lets the hand review
sort it out. That is a hedge, not an answer.

### 13. Which hiring philosophy governs screening. Peter.

These cannot all be true at once:

- One document says conscientiousness proxies matter, including GPA, school
  and a traditional resume.
- Another says interview charisma is a *negative* predictor and cognitive test
  scores have no predictive power here.
- CCAT is the live gate today.

The scoring signals currently follow the second document, because it is the
one backed by named outcomes at this company.

---

## The ones that block the inbound half, not this machine

### 14. The platform cause test. Lulu. Run it first.

Three LinkedIn accounts are burned for posting: Emi's, then Peter's, then
Bailey's. The root cause is unknown. Two candidate explanations:

- Identity contamination. A clean entity with a clean owner and card fixes it.
- The postings themselves. A new entity gets burned the same way and you paid
  for it.

The test: post one normal full-time role from a clean entity, from a browser
profile and IP Peter has never used, on an unlinked card. Wait 14 days.
Survives means the first. Removed means the second.

Cost of the test: one job posting. Cost of skipping it: a burned entity and
six weeks.

Correct one fact while you are there. Sunbird Systems LLC exists, EIN
33-2384783. "We are not incorporated" is true of Viewline Ventures only.

### 15. The posting entity for Indeed. Gary Kondler, then Peter.

The idea of using "a third party's incorporated entity we just use for
posting" is the nominee route. `brand-opsec-sop.md` marks it [MISREP-RISK] and
routes it to Kondler. Ask before, not after. Platform verification asks for
owner identity, so the version that survives is an entity genuinely owned by
someone genuinely in the operation. The related constraint is on file:
incorporation for Indeed "needs to not be tied to Peter".

### 16. Credibility assets. Peter.

There is no Viewline website and no candidate deck. The LinkedIn company page
needs a bio and employees added. A cold email from an entity with no website,
offering a 1099 contract, reads as a scam. Build them, or decide to send
anyway with eyes open.

### 17. Housekeeping, each small and each real.

- **Delete the plaintext password from the sourcing doc.** `asdf1234!A` is the
  shared default for Miriam, Lulu and May. Move to a password manager and
  force a reset. It is not stored in this repo.
- **Lulu's job board list.** Referenced in the sourcing doc, written down
  nowhere. It is the channel for every seat and country this machine will not
  email.
- **Which careers URL is live.** `careers.sunbirdsystems.com/quanttrader` and
  `sunbirdsystems.com/careers/quantitative-trader` both appear in the same
  document. One is stale and outbound cannot link to a guess.
- **Which posting tab is live.** Fifteen near-duplicate snapshot tabs, no
  current marker, Posted Date empty everywhere.
- **One canonical public title per role.** One internal role is posted under
  five public titles at different comp bands in the same city. A candidate who
  receives two of them can see it.
- **Seven empty tabs.** Director of Operations, Chief of Staff, Project
  Manager (Quant), Executive Assistant, Customer Service, Finance and one
  unnamed tab rendered empty in the export. They may hold answers to the
  questions above. Re-export or re-read them before treating `SOURCE-BRIEF.md`
  as complete.

---

## The book-then-cancel step. Decided, recorded here.

The sourcing doc describes letting everyone book, then re-checking the profile
and cancelling the ones that are not a fit, with an apology. The outbound SOP
argues against it: it makes angry people, and angry people write the public
complaints that are one plausible cause of the platform problems above.

Peter asked for the doc version, so it is built. Both halves are here:

- The booking form takes four required questions, which is the gate that
  avoids most cancellations. Use it.
- `outbound bookings triage` re-checks every booker and suggests confirm or
  cancel. Cancelling always sends the apology and warns inside twelve hours.

The default is a person deciding one at a time. `--auto` acts on every
suggestion. Do not use `--auto` until the suggestions have been right for a
week.

---

## What was assumed to keep building

Where a fact was missing, the code marks it rather than inventing it.

| Assumption | Where | How to change it |
|---|---|---|
| US only sending | `compliance.allow_countries` | `COMPLIANCE.md`. Take Canada and the EU to counsel first. |
| Comp goes in email one | `role.comp_in_email` | Set false in the role file if you disagree |
| Three emails, days 0, 4 and 8 | `sending.step_gap_days` | Settings |
| 18 a day per mailbox, two mailboxes, shared across roles | `sending.*` | Settings |
| Head of Operations, Engineer and ops generalist are live; the other five are drafts | role `status` | One word per role file |
| The T1 line is "a small trading firm in alternative assets" | templates and `content/jd/` | See question 7 |

---

## Two disagreements with the brain hiring pack, on purpose

Both repos were built the same day from the same crawl and they read one
document differently. Neither is a mistake. Recording both so nobody
"fixes" one into the other without deciding.

**1. The Head of Operations band.** Hiring Sprint Q1 (content Mar 2026)
carries several ops-leadership lines. This repo took the Director of
Operations line: `$135,000 to $175,000 base plus 0.5%-1.5% equity`. The
brain pack took the COO line: `$180,000 to $250,000+ plus significant
equity`.

Both figures are in the source. Which one applies depends on an unmade
decision: whether this seat is a Director of Operations or a COO. The
same document also gives VP of Operations at `$150,000 to $200,000`,
which sits between them.

**Consequence if we get it wrong.** Too low and a genuine COO-calibre
operator does not reply, which is the failure this search has already had
four times. Too high and we anchor a Director-calibre candidate above
what the seat is worth. The band is in email one, so this is decided
before the campaign runs, not after.

**2. The posted title on the quant seat.** This repo posts `quant-program-
manager` as **Technical Program Manager**. The brain pack posts it as
**Quantitative Team Manager** and explicitly rejects any "PM" title,
because PM reads as product manager to half the pool and project manager
to the other half.

Both are right for their channel, and this is deliberate rather than
drift:

- **Outbound writes to a named person.** Technical program managers are a
  genuinely good background for this seat, and the subject line has to
  read as their job. That is the whole point of the title portfolio.
- **A job board posting is read by strangers.** There, "Technical Program
  Manager" attracts a population that will be disappointed by week three.

Keep them different. If they are ever collapsed into one, collapse toward
the brain pack's title for anything public and keep the TPM framing for
the outbound sequence only.

Full title reasoning: `brain:projects/sunbird/hiring/common/title-portfolio.md`.

---

## Recorded 2026-08-30: five roles were live on a guessed salary

`docs/COMP.md` grades every band by confidence and is honest about it:
four are **High**, four are **Medium** ("my guess"), one is **Low** ("my
guess. No source anywhere"). All nine were `status = "live"` with
`comp_in_email = true`.

That is a guessed salary going into a cold email to a named senior
operator. An email cannot be edited after it is sent, and the number is
the first thing the reader looks at, so a wrong band is a retraction to
exactly the person we were trying to impress. The hiring pack applies the
same rule to job-board rows, where it matters less
(`brain:projects/sunbird/hiring/common/hiring-system.md` §6 rule 2).

**The rule now.** A role may be live with comp in the email only if
`comp_confidence = "high"`. `outbound/config.py` raises `ConfigError` on
anything else, so the pipeline cannot start with a guessed number in it.
Every role file now carries `comp_confidence`, copied from `COMP.md`.

**Live:** head-of-operations, chief-of-staff, quant-program-manager.
**Draft, pending Peter's number:** controller, engineer, brand-and-funnel,
ops-generalist, business-systems-lead, fulfillment-specialist.

Getting one number turns one campaign back on. `OUTBOUND-PLAYBOOK.md` §8
runs them one at a time anyway, so the three live roles cover the queue
for about nine weeks. This costs nothing today.

## Recorded 2026-08-30: three bands disagree with the hiring pack

Neither side is obviously right and both are assumptions, so nothing was
silently reconciled. All three are held at draft until Peter answers.

| Seat | This repo | The hiring pack | Note |
|---|---|---|---|
| Engineer | $120,000 to $160,000, anchored on the incumbent | $5,000 to $10,000 a month, interpolated from `costs.csv` | $60k to $120k against $120k to $160k. The ranges barely touch. The incumbent anchor is the better evidence, but `costs.csv` is the only figure derived from payroll |
| Controller / Head of Finance | $140,000 to $180,000 | $130,000 to $180,000 | A $10,000 gap at the floor. Small, and it would still be two numbers in two documents |
| Fulfillment Specialist | $80,000 to $105,000 | $90,000 to $160,000 posted, $90,000 target | See below. This may not be the same seat |

## Recorded 2026-08-30: the fulfillment-specialist seat identity

`config/roles/fulfillment-specialist.toml` is titled **Technical Support
Specialist** and describes 15 entry seats, hybrid, with daily local
travel and a QA and KYC keyword set. In the hiring pack that is the
**Quantitative Trader** seat, at 15 seats and the same shape. The pack's
actual Technical Support Specialist is a device-setup role at $29 to $31
an hour, and it owns that title
(`brain:projects/sunbird/hiring/common/title-portfolio.md` §5, collision
1: two seats never share a title).

So this file may be emailing 800 people about seat A under seat B's
title, at a band that matches neither. Held at draft.

It also carried its own instruction not to do what it did: *"Comp varies
BY CITY. Do not put a single band in the email. Set the band per search,
or split this into one role file per metro before going live."* It had
one band, `comp_in_email = true`, and `status = "live"` across seven
metros.

**To turn it back on**, three answers are needed: which seat this is,
which title it posts under, and the band per metro.

---

## Recorded 2026-08-30: never mention equity

Peter's ruling, verbatim: *"I don't think I've ever talked about equity. I
don't think that is supposed to be mentioned... Never mention equity.
It's not really something we're looking to do. Incentives on the upside
are definitely possible."*

Every equity line in this repo is gone, replaced with performance upside.
The quotes further up this file that cite the March 2026 source document
are **left as they are on purpose**: they record what that document says,
and rewriting them would falsify the record. Do not re-derive an offer
from them.

The standing rule lives at
`brain:projects/sunbird/hiring/common/hiring-system.md` §6 rule 3, and
`brain:projects/sunbird/hiring/check.py` fails on the word.

## Recorded 2026-08-30: the controller campaign is closed, not drafted

Peter: *"we're not really looking for a head of finance."*

`evidence/digests/03-peter-greg-drive-title-peter-greg.md` in the brain
repo, created 2026-08-19 and modified 2026-08-25, is the newest document
in the corpus. It records a named candidate proposing **$12,500 a month
as Finance Lead**, fractional rather than salaried, scoped to the
accounting firm, the day-to-day finance and fund transfers, the
dashboards and fund recovery.

That negotiation was live eleven days before this campaign was built to
recruit for the same seat at $140,000 to $180,000. The campaign was built
without reading it.

`status = "closed"`, not `"draft"`, because this is not waiting on a
number. It is not a search.

## Recorded 2026-08-30: the comp sanity check that was skipped

Peter: *"Many of these salary bands are much higher than what's provided.
You should have used the most recent informal message. That's one of the
most recent sources. You should have used that as a sanity check."*

He is right, and the failure is specific rather than general. The bands
here were derived from `costs.csv` and the March 2026 hiring document.
The Peter <> Greg doc is newer than both, and the brain repo's own digest
of it says, in writing: *"where this doc contradicts anything older in
the tree on comp, staffing, revenue, or the points formula, this doc
wins."* It was crawled, digested, and then not used.

**The rule that follows:** before publishing any band, check it against
the newest document that mentions the seat, not the most authoritative-
looking one. Recency beats format. A chat log from last week beats a
finished scorecard from March.

Two bands in this repo are still above their model point and are held at
draft: engineer ($120-160k against a $108k model point) and
brand-and-funnel ($110-150k against $96k).
