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
Workable job, Ukraine privacy review and sending infrastructure are ready.

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
2. Create the dedicated recruiting mailbox.
3. Fix DKIM and DMARC on the sending domain.
4. Start the mailbox warm-up.
5. Create one Workable job and record its shortcode and `Sourced` stage.
6. Keep Sunbird's existing interview and one-hour work simulation as the two
   selection gates. Copy the simulation instructions into Workable; do not
   rebuild the exercise here.
7. Connect the positive-reply handoff to Workable. The preferred path is the
   Workable API with `sourced = true`; a daily ATS CSV import is acceptable for
   the pilot.
8. Build a 50-person Ukraine pilot list, beginning with Lviv and expanding only
   if the profile quality is weak.
9. Run Prospeo and MillionVerifier. Measure the match rate and bounce risk.
10. Send five emails per day for the first three days, only after the Ukraine
    privacy basis and candidate notice have been reviewed.
11. Read every reply. Stop if reply rate is under 3% after 60 sends or bounce
    rate is over 3%.
12. Increase the list only after the pilot produces qualified work samples.

## Do not automate these decisions

- What "similar to Helen" means.
- Whether a profile deserves the work sample.
- Whether the work sample passes.
- Whether to make an offer.

The system may sort and draft. A person makes each decision.
