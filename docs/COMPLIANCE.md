# Compliance

Not legal advice. This file records optional controls and the small set of
low-friction protections that remain enabled.

## The short version

There is no global country restriction. Peter removed the inherited US-only
default on September 4, 2026. Each role's searches determine its candidate
markets. The country allow/block mechanism remains available but is off by
default.

The system still includes an unsubscribe link, a postal address and permanent
suppression after an opt-out. These cost essentially nothing and are useful
deliverability and candidate-experience controls regardless of jurisdiction.

The country-specific discussion below is retained as background for a later
review. It is not a current launch gate.

## United States: CAN-SPAM

Commercial email is allowed without prior consent. Four conditions matter here.

| Condition | What the code does |
|---|---|
| No false or misleading headers | The From and Reply-To come from `identity` in settings. Keep them true. |
| No deceptive subject line | Yours to check. The linter fails an exclamation mark and promotional openers. |
| A working opt out route | Every rendered body must contain "unsubscribe". A message without it is refused. |
| A valid physical postal address | Every rendered body must contain `identity.postal_address`. A message without it is refused. |

Two more that are yours, not the code's:

- Honour an opt out within 10 business days. Do it the same day:
  `outbound suppress <address> --reason "asked to stop"`.
- Keep the opt out route working for at least 30 days after the send.

A reply saying "no thanks" is an opt out. Treat it as one.

Some states add their own rules. California and a few others have stricter
provisions on deceptive content. Nothing in this flow relies on deception, so
the federal rules are the binding ones.

## Canada: CASL

Consent is required before a commercial electronic message. Penalties reach
ten million dollars. The exemptions are narrow, and a cold recruiting email to
a person who has never heard of you does not fit one cleanly.

**Do not cold email Canada.** `CA` is on the block list.

This matters, because the Canada launch is live and Canada is the priority gap
for quant and tech support hiring. Route Canadian hiring through job boards,
referrals and a local recruiter. The block is on outbound email only.

## European Union and Poland

GDPR plus each country's own electronic communications rules. Poland is among
the strictest EU states on unsolicited email to individuals, and the Poland
recruiting node is live in the plan.

**Do not cold email the EU.** Every EU state is on the block list.

For Poland, use Pracuj.pl, NoFluffJobs, OLX Praca and a local recruiter. That
is a channel decision, not a legal workaround.

## United Kingdom

PECR plus UK GDPR. Corporate subscribers are treated differently from
individuals, and a work address at a limited company is arguably a corporate
subscriber. The position is arguable, which is not the same as safe. `GB` is
blocked by default. Change it only with advice.

## What "unknown country" means

`outbound score` sets a country from the location string on the profile. If it
cannot, the country is empty and the candidate is disqualified with
`blocked_geo`. That is deliberate. Fix it by putting a real location in the
list, not by loosening the gate.

## Data protection, whichever regime applies

You are holding personal data about people who did not ask you to.

- `data/` is gitignored. Do not commit a list, a database or an export.
- Do not put a candidate list in a shared drive or a chat message.
- Delete a person's record on request. There is no command for it on purpose,
  because it is rare and should be deliberate. Suppress the address first so
  they cannot be re-imported, then delete the row by hand.
- Do not enrich personal email addresses. The Apollo adapter sets
  `reveal_personal_emails` to false and the RocketReach adapter drops
  addresses typed as personal.

## Enabling a country gate later

Set `compliance.enforce_geo_block = true`, fill `allow_countries`, and optionally
fill `block_countries`. When enforcement is off, an empty allow list does not
block sending.
