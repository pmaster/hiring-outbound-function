# The first two weeks

An ordered plan. Everything before day 11 costs no money and sends no email.

The long pole is the domain: DKIM, DMARC and ten days of warm up. Start that
on day one whatever else happens, because nothing can send until it is done
and no amount of list building shortens it.

## Day 1, about two hours

**Fix the DNS.** `viewlineventures.com` has SPF and Google Workspace MX and
neither DKIM nor DMARC. Cold email from an unsigned domain goes to spam
silently: no bounce, no signal, the replies just never come.

    python3 -m outbound dns viewlineventures.com

- **DKIM.** Google admin console, Apps, Google Workspace, Gmail, Authenticate
  email. Generate the record, publish the TXT at
  `google._domainkey.viewlineventures.com`, wait for it to propagate, then go
  back and press **Start Authentication**. Skipping that last step leaves the
  record published and nothing signed, which is the usual mistake.
- **DMARC.** TXT at `_dmarc.viewlineventures.com`:
  `v=DMARC1; p=none; rua=mailto:dmarc@viewlineventures.com`

**Create the sending mailbox.** One dedicated mailbox on viewlineventures.com,
not one anybody relies on. Two if you want the headroom.

**Set up the tool.**

    python3 -m outbound init
    # config/settings.toml: postal_address is the one field that cannot be
    # guessed. Use the registered address of the entity doing the hiring.
    python3 -m outbound doctor --dns

**Start the warm up clock.** Ten days at low volume. The ramp in settings does
this for you once sending begins; what matters today is that the mailbox
exists and the records are right.

## Day 1, another hour

**Build the screener page.** Ten minutes, not fifteen. Put the four questions
on it as **required** questions:

    python3 -m outbound questions head-of-operations

Reviewing four answers each morning is far cheaper than cancelling a booked
call. Put the URL in `booking.screener_url`.

**Publish the job descriptions.**

    python3 -m outbound pages

Upload `site/` to viewlineventures.com. Then point the unsubscribe form at
something that records an address.

## Days 2 to 4: build one list

One role first. Not three. **Head of Operations**, because it is the seat that
has failed four times and because the play is reusable once it works.

    python3 -m outbound search head-of-operations

Run each query in the browser. Target 600 to 900 raw profiles; you will cut
about half. Read every profile. Keep the person only if the work history shows
a finished hard thing.

**Do not connect a real LinkedIn account to a scraper.** Three accounts here
are already burned for posting and the root cause is unknown.

    python3 -m outbound import head-of-operations list.csv
    python3 -m outbound score  head-of-operations
    python3 -m outbound audit  head-of-operations

Read the audit. If it says 85 percent was rejected, the search is too broad or
a disqualifier is too aggressive. If it says 12 percent, the filter is not
filtering.

## Days 3 to 5: review, in the background

    python3 -m outbound review head-of-operations --export review.csv

Work through it in a spreadsheet. The tool quotes the profile lines that made
each score, so the slow part, finding the one specific thing to say, is mostly
done for you. Write the note. If you cannot write it in one sentence, reject
the person; a generic opener is worse than no email.

    python3 -m outbound review head-of-operations --import-file review.csv

## Day 5: pick the vendors

    python3 -m outbound enrich head-of-operations   # needs an enrichment key
    python3 -m outbound verify head-of-operations   # needs a verifier key

At 300 people this decision is worth about fifty dollars. Buy the smallest
plan of one enrichment vendor and one verifier, run fifty people through, and
count the match rate and the bounce rate yourself. `docs/VENDORS.md` says what
to check; `docs/VENDOR-APIS.md` has the verified endpoints.

## Day 11: the first send

Warm up is done. Before anything goes to a candidate:

    python3 -m outbound doctor head-of-operations --dns
    python3 -m outbound send head-of-operations --test-to you@gmail.com --live
    python3 -m outbound send head-of-operations --test-to you@outlook.com --live

Read both. Raw headers: SPF, DKIM and DMARC must all say pass. Then read the
email as a candidate would.

Then:

    python3 -m outbound queue head-of-operations
    python3 -m outbound send  head-of-operations --live

Five a day for the first three days, whatever the ramp says, because you want
to read every reply to the first fifteen personally.

## Days 12 onwards: the loop

    scripts/daily.sh --live

Then, by hand, every morning, about thirty minutes:

    python3 -m outbound inbox                   # what people said
    python3 -m outbound bookings triage         # who booked, and are they a fit
    python3 -m outbound review head-of-operations
    python3 -m outbound report

## What good looks like

On a hand built 300 person list, founder sent:

| Number | Expected |
|---|---|
| Replies | 8 to 15 percent, so 25 to 45 |
| Positive | 3 to 6 percent, so 10 to 18 |
| Real conversations | 5 to 12 |
| Worth a work sim | 2 to 5 |

That fills one seat.

## When to stop and think

- **Under 3 percent reply after 60 sends.** The list or the copy. Read ten of
  your own sent emails in `data/outbox/`. Usually it is the first line: a note
  that could have been written about anyone.
- **Bounce rate over 3 percent.** The tool halts sending on its own. The list
  source or the verifier is wrong.
- **Bookings that are not a fit.** The screener questions are not doing their
  job. Tighten them before you start cancelling calls, because a cancelled
  call makes an angry person and this operation cannot afford more of those.
- **Everything works and the seat is still open after 300 people.** The
  problem is the offer or the process, not the outbound. That is a different
  conversation and a better one to be having.

## What this does not do

Job boards, campus and referrals. Cold email fits senior and rare seats. The
volume seats are blocked by platform access, not by channel count, and the
offshore seats are blocked by consent law. `docs/COMPLIANCE.md` has the
geography.
