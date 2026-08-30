# Open decisions

What is not settled, who settles it, and what it blocks.

Written 2026-08-30 while building the pipeline, then rewritten after a
recursive crawl of 40 Google Drive files. The crawl output, with a fileId on
every claim, is `SOURCE-BRIEF.md`. Read that when an answer here is not enough.

Everything here was hit during the build and worked around, so the code runs.
None of it is a code problem.

---

## The three that block every live send

### 1. Comp numbers. Set, as assumptions. Peter to correct.

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
    comp = "$135,000 to $175,000 plus equity"

The demo file has invented numbers so the pipeline runs. They are not
proposals. Replace them.

### 2. viewlineventures.com has no DKIM and no DMARC. Whoever holds the DNS.

**Decided:** Peter chose viewlineventures.com on 2026-08-30, and the code
records that. What follows is a concrete, checked problem on that domain.

Run it yourself:

    python3 -m outbound dns viewlineventures.com

As of 2026-08-30 it returns:

| Record | State |
|---|---|
| SPF | **pass**. `v=spf1 include:spf.efwd.registrar-servers.com include:_spf.google.com ~all` |
| MX | **pass**. Google Workspace. |
| DKIM | **missing**. No key at any common selector. |
| DMARC | **missing**. No record at `_dmarc`. |

An unsigned domain with no DMARC policy is treated as suspicious by every
large mailbox provider, and cold email from one lands in spam without a
bounce, so nothing tells you it happened. This is the single highest value
half hour of work before the first send.

**The fix, both steps.**

1. **DKIM.** The mail is on Google Workspace, so: Admin console, Apps, Google
   Workspace, Gmail, Authenticate email. Generate a new record for
   viewlineventures.com, take the TXT value it gives you, publish it at
   `google._domainkey.viewlineventures.com`, wait for it to propagate, then go
   back and press Start Authentication. Missing that last step is the common
   mistake: the record exists and nothing is signed.
2. **DMARC.** Publish a TXT record at `_dmarc.viewlineventures.com`:

       v=DMARC1; p=none; rua=mailto:dmarc@viewlineventures.com

   Start at `p=none`. Read the reports for two weeks, confirm everything
   legitimate is passing, then move to `p=quarantine`. Going straight to
   quarantine or reject will silently drop your own mail.

Then `python3 -m outbound dns` again, and send one seed email to a Gmail
address and one to an Outlook address and read the raw headers. All three of
SPF, DKIM and DMARC must say pass. `outbound doctor --dns` folds this check
into the preflight.

For contrast, sunbirdsystems.com already has DKIM (Zoho) and a DMARC record,
though its DMARC has no reporting address, so it is also blind.

### 3. The sending domain choice itself. Settled, recorded here.

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

### 4. Job description pages. Done, needs hosting.

All nine are written and build to static HTML:

    python3 -m outbound pages

That writes `site/` with a careers index, nine role pages and an unsubscribe
page. Self contained, no external requests, light and dark. Peter said hosting
is no problem. Upload `site/` to viewlineventures.com, then the `jd_url` in
each role file already points at the right path.

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

### 13. Which hiring philosophy governs screening. Peter has ruled.

Peter's position (2026-08-30), settling this: high intelligence is necessary
but not sufficient for most of these seats. A cognitive floor is a real gate;
above it, intelligence stops sorting and conscientiousness, accountability and
domain fit do the work.

An earlier draft here read one source document too literally and concluded
that "cognitive test scores have no predictive power." That was the build's
reading, not Peter's, and it was drawn too fast. It is overruled. CCAT stays a
live gate. What the source documents actually support, and what the scoring
now follows:

- Intelligence proxies are necessary-but-not-sufficient positive signals, not
  decisive ones. MBB and IB pedigree, a selective-program alum, a strong
  analytics or quant track, and a passing CCAT clear the floor. They do not by
  themselves make a hire.
- Conscientiousness proxies matter and are weighted: GPA, school and a
  traditional resume less for their prestige than for the organization and
  professionalism they stand in for (Peter's words). Leadership roles (club
  president, team captain) proxy accountability.
- Domain interest, an operating seat over a pure-advisory one, and a real
  track of shipping outweigh raw pedigree once the floor is cleared.

The scoring reflects this: pedigree and cognitive-proxy signals carry real but
bounded weight, an agency-only or advisory-only profile is penalized rather
than rewarded, and no signal treats charisma as a negative. The one claim that
was dropped is "cognitive scores do not predict" — they gate.

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

## A known residual: bare 2-letter location tails

Country is inferred from the location string when a profile has no explicit
country field. A location like "City, XX" where XX is a bare 2-letter code is
irreducibly ambiguous: CA is both California and Canada, DE both Delaware and
Germany, MT both Montana and Malta. The tool resolves this in three layers,
in order: an explicit country field wins; then a spelled-out country name or a
known foreign city ("Toronto", "Berlin") classifies to that country; then a
bare tail that is a US state code reads as US, and a bare tail that is an
unambiguous foreign code (PL, FR, GB, and the like) reads as that country.

The residual: an obscure foreign city in a country whose code also shadows a
US state (Canada, Germany, Malta), written as a bare "City, CA/DE/MT" with no
country field and no recognized city name, reads as US. In practice this does
not happen, because the real sourcing providers (Apollo, Apify) supply an
explicit country and the tool sources with a US geography filter, so the
bare-tail path is only reached by a hand-imported CSV. If you import such a
CSV, include a country column. Unknown countries are refused, which is the
safe direction.

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
