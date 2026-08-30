# The AI screen, and the two flows it enables

This answers three things you asked: how your picture of the flow compares to
what the machine does, what the evaluator actually judges, and how to run the
high-volume shape you described.

## Your flow, next to what is built

You described: find profiles at scale, let AI read each one, find an email,
send one email with an intro, a JD link and a screener link, cap the send,
take the bookings, and cancel the false positives with an apology. Here is
where that already matches and where it did not.

| Your step | In the machine | Gap |
|---|---|---|
| Find profiles at scale | `search` stage. Apify or Apollo adapters, or a VA drops a CSV into `import`. | None. A VA fallback works today. |
| A person reads each one | Was the only path. Now there is a second: the `evaluate` stage reads each profile with a model. | Closed. See below. |
| Find an email, with a confidence | `enrich` then `verify`. Enrich returns a confidence; verify returns valid, risky, catch-all or invalid. | None. |
| One email: intro, JD link, screener link | Was a three-step sequence. Now `sending.max_steps = 1` makes it one email. | Closed. |
| Send under a smart daily cap | Daily cap, shared-domain cap, warm-up ramp, bounce circuit breaker. | None, but see the deliverability note. |
| 200+ a day | The caps are config. The number is not the constraint; the domain is. | Open. See "Volume". |
| Interview everyone, or re-check and cancel | `bookings triage`, then `bookings decide <id> cancel --reason "..."` sends the apology. | None. The re-check is still by hand. |

The one real disagreement was screening. The build assumed a person writes one
specific line per candidate. You want the model to do that reading. Both now
exist and you pick per role.

## What the evaluator judges

The screen does not invent a standard. It reads the role's own config: the
titles wanted and excluded, the seniority band, the company headcount, the
years of experience, the keywords, the industries, and every scoring signal
with a positive weight. It returns four things:

- a fit score from 0 to 1,
- a verdict of strong, maybe or weak,
- short reasons, the evidence for the verdict,
- the one specific personal note for line one of the email.

It follows the screening doctrine you set (`DECISIONS.md` #13): intelligence is
necessary but not sufficient. A strong pedigree with no operating track is a
maybe, not a strong. A real track of building and running the thing the seat
needs is what moves it to strong.

So "what should I be evaluating" has a plain answer: fit against the seat's ICP,
gated by a cognitive floor, decided above the floor by a real track and by
accountability and domain proxies. The rubric lives in the role TOML, not in
the model, so you change it by editing config.

## The two modes

Set `evaluation.mode` in `settings.toml`.

**assist.** The screen drafts the note and records the verdict, but a person
still approves. This is your founder flow, with the slow part done: the note is
written, the reviewer confirms or overrides. Use it for the senior seats where
the send is from you and the list is small.

**auto.** The screen approves a strong fit with its drafted note, rejects a
weak one, and sends a maybe to the review pile. No person writes a note. This
is the volume flow. Use it for the high-count seats.

Both are off until you turn them on: `evaluation.provider` defaults to `none`.
Set it to `anthropic`, put `ANTHROPIC_API_KEY` in `.env`, and pick a mode. The
`dryrun` provider runs the whole thing offline for a test, using the heuristic
score in place of the model.

## The one-email flow

`sending.max_steps = 1` caps every sequence at the first email. That email
carries the intro, the JD link and the screener link. No follow-ups queue. Set
it back to 0 to use the full three-step sequence again. The templates stay in
place either way, so this is a toggle, not a rewrite.

## Volume, and the one real limit

The cap is a number in config. Raising it is one line. The limit is not the
number, it is the domain. viewlineventures.com is new, and it has no DKIM and
no DMARC yet (`DECISIONS.md` #2). Sending 200 cold emails a day from a cold,
unauthenticated domain is how a domain gets blacklisted in a week, and then no
email from it lands anywhere.

The order that gets you to 200 a day without burning the domain:

1. Add DKIM and DMARC. Run `outbound dns viewlineventures.com` until all four
   records pass.
2. Warm up. The ramp is already in the config. It starts low and climbs over
   weeks. Do not skip it.
3. Split the volume across mailboxes and, better, across a second sending
   domain, so no single domain carries all 200.
4. Watch the bounce rate. The circuit breaker stops the send at 3 percent. A
   climbing bounce rate means the list quality or the warm-up is wrong, not
   that the breaker is too strict.

A one-email, no-personalization, 200-a-day cold send also answers at a lower
rate than a personalized founder send. You are trading reply rate for volume on
purpose. That is a fine trade when the seat has many good candidates and the
screener call is cheap. It is a bad trade for a seat with fifty possible people
in the country. Pick the shape per seat.

## The false-positive cancel

When a booking comes in from someone the screen or the list got wrong, re-check
the profile, then:

    python3 -m outbound bookings decide <id> cancel --reason "..."

That sends the apology and frees the slot. The re-check is by hand today. An AI
re-check of a booker is a small addition on the same evaluator, if you want it.
