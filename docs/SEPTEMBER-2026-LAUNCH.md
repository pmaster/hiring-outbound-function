# September 2026 hiring launch

This is the launch path for the next cohort. The target is five to ten hires
similar to Helen at about $3,000 per month.

## The Helen role

The September 4 operations discussion settles the broad role. This is not the
existing US `ops-generalist` role. It is an offshore operations partner paired
with one or more quants to improve focus, follow-through and process execution,
and to build bench strength for the done-with-you operating model.

Working definition:

- Working title: Operations Partner, Quant Support. Peter can change the public
  title before the Workable job is published.
- Target cohort: five to ten hires.
- Reference candidate: Helen, based in Lviv, Ukraine.
- Geography: Eastern Europe first, then LATAM if the first source pool is weak.
- Pay anchor: about $3,000 per month. The operations discussion describes the
  budget as roughly $20 per hour; these are not exactly the same at full-time
  hours, so the offer language must use one convention.
- Hiring process: team interview, then Sunbird's existing one-hour work
  simulation. Do not build another assessment.
- Core job: work alongside a quant, keep the day moving, close verification and
  cash-out follow-ups, notice blockers early, maintain the operating record and
  compare methods with other operations partners.
- Operating shape: partners rotate through direct pairing with quants while
  asynchronously supporting a pod or the general team. The exact remit is
  intentionally expected to change during the pilot.
- Hours: some regular Eastern-time overlap is required, but a full US schedule
  is not.
- Engagement: contractor. This is the default for all Sunbird roles.
- Pilot scorecard: points per quant per working hour, points per client, focused
  quant work hours, client rapport and preventable mistakes. Compare each
  measure with that quant's pre-pairing baseline rather than setting arbitrary
  absolute targets before the pilot produces data.

The dedicated role file is `config/roles/quant-operations-partner.toml`. Do not
reuse `ops-generalist` or `quant-program-manager`; both are US roles at
materially different pay and scope. Keep the new role in `draft` until its
Workable job and sending infrastructure are ready.

## Use this stack

| Stage | Tool | Decision |
|---|---|---|
| Find people | Apollo search, or a hand-built LinkedIn list | Use vendor data for volume. Do not give a scraper a LinkedIn cookie. |
| Find work email | Prospeo | The adapter accepts a public LinkedIn URL or a name plus company. |
| Verify email | MillionVerifier | Keep this as a separate gate before every send. |
| Send | SMTP first | This repo already schedules the sequence and stops it on replies. A second sequencer duplicates that work. |
| Book | Existing scheduling path | Keep the first interview short. Do not add a new assessment or scheduling vendor if Workable already handles this. |
| Track | Workable | Create positive replies as `Sourced` candidates in one job. This repo retains delivery and suppression history only. |

Do not buy Instantly, Smartlead, and ListKit together. They overlap. If inbox
warm-up becomes the hard part, use one of them for the inboxes and make one
system own the sequence. The current safe path is SMTP because this repo owns
the sequence.

## Settings

Run:

    python3 -m outbound init

Then put this provider block in `config/settings.toml`:

    [providers]
    search  = "apollo"
    enrich  = "prospeo"
    verify  = "millionverifier"
    send    = "smtp"
    booking = "calendly" # replace only if the existing interview link differs
    replies = "imap"
    enrich_waterfall = ["prospeo", "apollo"]

    [providers.prospeo]
    only_verified_email = false

    [providers.calendly]
    organization = "https://api.calendly.com/organizations/CHANGEME"
    user = "https://api.calendly.com/users/CHANGEME"

Put these keys in `.env`:

    APOLLO_API_KEY=
    PROSPEO_API_KEY=
    MILLIONVERIFIER_API_KEY=
    CALENDLY_TOKEN=
    SMTP_HOST=
    SMTP_PORT=587
    SMTP_USER=
    SMTP_PASSWORD=
    IMAP_HOST=
    IMAP_PORT=993
    IMAP_USER=
    IMAP_PASSWORD=

Never put keys in `settings.toml`.

## Launch order

As of September 4, `viewlineventures.com` publishes SPF, but Google Public DNS
returns `NXDOMAIN` for both `_dmarc.viewlineventures.com` and
`google._domainkey.viewlineventures.com`. DKIM and DMARC are therefore real
go-live blockers, not checklist hygiene.

1. Define the Helen role. Keep it draft.
2. Buy 20 pre-warmed sending accounts across separate recruiting domains in
   Instantly. This avoids waiting on the main domain and minimizes setup work.
   Start each at five messages a day and move toward 20 to 25 per day as its
   health stays strong. Keep replies routed to a mailbox the recruiting owner
   reads.
3. Fix DKIM and DMARC on the main domain separately. It is still worth fixing,
   but it no longer blocks the pilot if the pre-warmed accounts are fully
   authenticated.
5. Create one Workable job and record its shortcode and `Sourced` stage.
6. Keep Sunbird's existing interview and one-hour work simulation as the two
   selection gates. Copy the simulation instructions into Workable; do not
   rebuild the exercise here.
7. Connect the positive-reply handoff to Workable. The preferred path is the
   Workable API with `sourced = true`; a daily ATS CSV import is acceptable for
   the pilot.
8. Build a 2,000-person Ukraine list, beginning with Lviv and then expanding
   nationally. Let the scoring and evaluation system rank it. A recruiting
   owner should spot-check 25 top profiles and 25 rejects, not hand-review all
   2,000.
9. Run Prospeo and MillionVerifier. Measure the match rate and bounce risk.
10. Plan on a 1.5 to 2 percent booking rate per unique delivered prospect. At
    2,000 prospects, that means 30 to 40 bookings. Five percent is excellent;
    one percent is a plausible downside.
11. Have the delegated recruiting owner read every reply. Review performance
    after 500 delivered prospects, but stop immediately if bounce rate exceeds
    3 percent.
12. Keep scaling while the booked candidates are reaching the work simulation.
    Do not wait for all 2,000 prospects to finish before opening the next list.

For Instantly pre-warmed accounts, use the account-level ramp in Instantly and
set the repository warm-up ramp to empty so two systems do not throttle the
same mailboxes:

    [sending]
    per_mailbox_per_day = 25
    mailboxes = 20

    [warmup]
    require_warmup_done = false
    ramp = []

## Do not automate these decisions

- What "similar to Helen" means.
- Whether a profile deserves the work sample.
- Whether the work sample passes.
- Whether to make an offer.

The system may sort and draft. A person makes each decision.
