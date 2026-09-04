# hiring-outbound-function — rules

Outbound recruiting for Sunbird's open full time seats. Companion to the brain
repo at `projects/sunbird/outbound-recruiting-sop.md`, which holds the doctrine
this code implements.

## Writing

- Simplified Technical English for anything operational: docs, runbooks,
  comments, CLI output. Short sentences. One idea each. Active voice.
  Imperative for steps. Consistent terms.
- No AI smell. Nothing here should read as machine written. Tells and the
  sweep process live in the brain repo at `topics/no-ai-smell.md`.
- No em dashes in anything a candidate will read. The linter in
  `outbound/compose.py` enforces this and will fail the render.
- Orwell's rules. No cliché, no long word where a short one does, cut every
  word you can.

## Code

- Standard library only. Python 3.11 or later. No dependencies, so this runs
  anywhere with no install step.
- Every stage is idempotent. Running a command twice must not send twice.
- Guard rails raise, they do not warn. A warning in a cron job is a warning
  nobody reads.
- Provider adapters know nothing about the pipeline. The pipeline knows
  nothing about a provider's JSON. `outbound/profiles.py` is the only place
  that maps a vendor's field names.
- Run the tests before every commit: `python3 -m unittest discover -s tests`.

## Data

- `data/` holds real people. It is gitignored. Do not commit a candidate list,
  a database, or an export.
- Secrets live in `.env` or the environment. Never in a config file, never in
  a role file, never in a commit.
- Never delete a suppression record.

## Sending

- Never send from `cornerstonegigs.com` or `sunrunlabs.com`. The code blocks
  both. Peter chose `viewlineventures.com` for FTE outreach on 2026-08-30.
  Use a dedicated mailbox, keep the volume low, and keep the decision record
  in the settings. `sunbirdsystems.com` remains a warned domain because the
  campus channel depends on it.
- Never connect a real LinkedIn account to a scraper.
- Geographic blocking is optional and off by default. Peter removed the
  inherited US-only restriction on 2026-09-04. Role searches, not a global
  country allow list, define the intended candidate markets.
