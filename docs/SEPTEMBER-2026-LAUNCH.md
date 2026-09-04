# September 2026 hiring launch

This is the launch path for the next cohort. The target is five to ten hires
similar to Helen at about $3,000 per month.

## One fact is still missing

Do not turn a role live until Peter states what Helen was hired to do and
where she is based. The current repo has several roles that could fit the
short description. They have different profiles, tests, laws, and outreach
copy.

Known:

- Target cohort: five to ten hires.
- Reference candidate: Helen.
- Reference pay: about $3,000 per month.
- Helen passed a team interview and a one-hour work sample.

Needed:

- Public role title.
- Three outcomes the person owns.
- Country or countries to source.
- The work sample Helen took.
- Three reasons Helen passed it.
- Work hours and time-zone overlap.
- Contractor or employee status.

Use `docs/ROLE-INTAKE.md` once those answers exist. Add a separate role file.
Do not reuse `ops-generalist`. That role is US-only, pays $70,000 to $95,000,
and asks for a different person.

## Use this stack

| Stage | Tool | Decision |
|---|---|---|
| Find people | Apollo search, or a hand-built LinkedIn list | Use vendor data for volume. Do not give a scraper a LinkedIn cookie. |
| Find work email | Prospeo | The adapter accepts a public LinkedIn URL or a name plus company. |
| Verify email | MillionVerifier | Keep this as a separate gate before every send. |
| Send | SMTP first | This repo already schedules the sequence and stops it on replies. A second sequencer duplicates that work. |
| Book | Calendly | The company already uses it. Put the role questions on the event as required fields. |
| Track | This repo, then Workable export | Keep one candidate record and one suppression list. |

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
    booking = "calendly"
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

1. Define the Helen role. Keep it draft.
2. Create the dedicated recruiting mailbox.
3. Fix DKIM and DMARC on the sending domain.
4. Start the mailbox warm-up.
5. Create the Calendly event and its required questions.
6. Put the work sample after the first short screen, unless Peter decides to
   send candidates to it first.
7. Build a 50-person pilot list.
8. Run Prospeo and MillionVerifier. Measure the match rate and bounce risk.
9. Send five emails per day for the first three days.
10. Read every reply. Stop if reply rate is under 3% after 60 sends or bounce
    rate is over 3%.
11. Increase the list only after the pilot produces qualified work samples.

## Do not automate these decisions

- What "similar to Helen" means.
- Whether a profile deserves the work sample.
- Whether the work sample passes.
- Whether to make an offer.

The system may sort and draft. A person makes each decision.
