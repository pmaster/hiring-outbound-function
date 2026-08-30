# Runbook

What happens each day, and who does it.

## Who owns what

| Person | Owns |
|---|---|
| Peter | Writes and sends the Head of Operations and Engineer emails. About 30 minutes a day for three weeks. |
| Lulu | The channel portfolio: job boards, the move off Dstribute, and the platform cause test. |
| Miriam or May | Builds and verifies the lists, and reviews the booking form answers each morning. |

The real constraint is not cost. The tool stack is under 0.1 percent of
payroll. The constraint is that this needs a person every working day.

## Before the first send

Work through `SETUP.md`. Then:

    python3 -m outbound doctor <role>

Do not start a list before the domain is warming. The wait is ten days and it
is the long pole.

## Build the list

Two to three days per role.

1. Print the queries.

       python3 -m outbound search head-of-operations

2. Run each search in the browser. Target 600 to 900 raw profiles for a 300
   person list. You will cut about half by hand.
3. Read each profile. Keep the person only if the work history shows a
   finished hard thing. Do not skip this. It is the whole edge.
4. Record the columns the import needs: `full_name`, `linkedin_url`, `title`,
   `company`, `location`. Add `company_headcount`, `company_domain` and
   `summary` when you have them.
5. Import and score.

       python3 -m outbound import head-of-operations list.csv
       python3 -m outbound score  head-of-operations

**Do not connect a real LinkedIn account to a scraper.** Some tools ask for
your session cookie. LinkedIn restricts accounts for it and this operation
cannot afford to lose LinkedIn access. Read profiles in the browser and take
email data from a vendor.

## The morning loop, about 30 minutes

1. **Review.** Read the queue. Approve with the one specific detail that goes
   in line one of the email.

       python3 -m outbound review head-of-operations
       python3 -m outbound review head-of-operations --approve 41 --note "You stood up the ops function at Kestrel from nothing."

   If you cannot write that line in one sentence, reject the person. A generic
   line is worse than no email.

   For a long queue, work offline in a spreadsheet instead:

       python3 -m outbound review head-of-operations --export review.csv
       # open it, click the profile links, fill in decision and personal_note
       python3 -m outbound review head-of-operations --import-file review.csv

   A blank `decision` is left alone, so you can do the file in two sittings.

2. **Enrich and verify.**

       python3 -m outbound enrich head-of-operations
       python3 -m outbound verify head-of-operations

   Addresses that come back risky or catch all wait for a decision. Accept
   them, or leave them out:

       python3 -m outbound verify head-of-operations --accept-risky

3. **Queue and send.**

       python3 -m outbound queue head-of-operations
       python3 -m outbound send  head-of-operations --live

   Run `send` without `--live` first to see what would go. The dry run writes
   the emails to `data/outbox/`.

4. **Replies and bounces.**

       python3 -m outbound replies sync

   This reads the sending mailbox over IMAP, marks anyone who answered, and
   suppresses hard bounces. Run it before `queue`, not after, so a follow up
   never goes to someone who already replied.

   Anything it misses, mark by hand:

       python3 -m outbound replies mark someone@company.com
       python3 -m outbound replies mark someone@company.com --kind unsubscribed

5. **Bookings.**

       python3 -m outbound bookings sync
       python3 -m outbound bookings triage

   Read each one. The suggestion is a number, not a decision.

       python3 -m outbound bookings decide 12 confirm
       python3 -m outbound bookings decide 13 cancel --reason "no operating seat" --live

   Cancelling always sends the apology. Cancel at least 12 hours ahead. If you
   are inside 12 hours, take the call. A late cancellation costs more than ten
   minutes.

6. **Hand the good ones over.**

       python3 -m outbound export --format ats

   That writes everyone who replied or booked, with their address, their
   profile link and the note you wrote about them. Import it into the
   applicant tracking system so the recruiting team sees one pipeline rather
   than two. Applying through a posting and being emailed cold are different
   intake paths and nothing else reconciles them.

7. **Read the report.**

       python3 -m outbound report

## Before you commit to a list

    python3 -m outbound audit head-of-operations

Everything it checks is cheap to fix now and expensive to fix after the first
hundred emails. It answers three questions: is the list big enough and how
long will it take, is anything in it that should not be written to, and is the
ICP doing what you meant.

Two of its warnings are worth reading carefully:

- **"85% of the list was rejected."** Either the search is too broad or a
  disqualifier is too aggressive. Both waste your time, in opposite ways.
- **"only 12% was rejected."** A filter that rejects almost nothing is not
  filtering. The score is sorting the queue but not shaping it.

`scripts/daily.sh` runs the audit for every live role first and skips any role
with a blocking problem.

## Automating the safe half

Steps 2, 3 and the booking sync are in one script:

    scripts/daily.sh --live

On cron, weekdays at 08:40 New York:

    40 8 * * 1-5 cd /path/to/hiring-outbound-function && scripts/daily.sh --live >> data/daily.log 2>&1

It runs `doctor` per role first and skips any role that fails, so a half
configured role cannot send. It never approves a candidate and never decides a
booking.

## What good looks like

On a hand built 300 person list, founder sent:

| Number | Expected |
|---|---|
| Replies | 8 to 15 percent, so 25 to 45 |
| Positive replies | 3 to 6 percent, so 10 to 18 |
| Real conversations | 5 to 12 |
| Worth a work sim | 2 to 5 |

That fills one seat. If you are three days in and under 3 percent reply, stop
and look at the copy and the list, not at the volume.

The sourcing doc estimates 5 to 10 percent of people who receive the email
will book. That number comes from a bulk campaign with a booking link and no
gate. With required booking questions the booking rate is lower and the show
rate is much higher. Optimise for conversations, not bookings.

## When something goes wrong

| Symptom | First thing to check |
|---|---|
| `doctor` fails | It names the setting. Fix that one thing. |
| Replies near zero | The personal note. Read ten of the sent emails in `data/outbox/`. |
| Bounces above 3 percent | Stop sending. The list source or the verifier is wrong. |
| Emails in spam | Check SPF, DKIM and DMARC pass on a seed send. Then check the volume ramp. |
| "domain cap reached" with little sent | Another role used the shared mailboxes today. The cap is per domain, not per role. Raise `sending.mailboxes` only if the mailboxes actually exist. |
| A send failed | It is retried on the next run, three times, then left as failed. `sqlite3 data/outbound.db "select * from messages where status='failed'"` |
| Cannot find emails | Add a second enrichment provider to `providers.enrich_waterfall`. |
| A person asks to stop | `outbound replies mark <address> --kind unsubscribed`. Same day. |
| A follow up went to someone who replied | `replies sync` did not run, or IMAP is not configured. Fix that first, it is the worst failure here. |

## Weekly

- Read `outbound report` for every live role.
- Check the bounce rate. Above 3 percent, stop and fix the list.
- Check the DMARC reports.
- Re-read the rejected pile for one role. If you are rejecting people you
  should be writing to, the ICP is wrong, not the people.
