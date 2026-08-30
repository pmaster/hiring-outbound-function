# Vendors

Which tool does which job, what to check before buying, and the one rule that
overrides price.

## The rule that overrides price

**Never connect a real LinkedIn account to a scraper.** Some tools, and many
Apify actors, run through a connected account or a pasted session cookie.
LinkedIn restricts accounts for it. This operation already cannot afford to
lose LinkedIn access, and the entire inbound channel depends on it.

Read profiles in the browser. Take email data from a vendor's own database.
The Apify adapter refuses an actor input that mentions a cookie unless
`cookie_actor_ok = true` is set on purpose.

That rule eliminates most of the cheap LinkedIn scraping market. What is left
is: search a vendor's own people database, or build the list by hand.

## Cost is not the constraint

Payroll is about $268,794 a month across fifty people. The whole tool stack
for this is in the low hundreds. That is under 0.1 percent of payroll.

Do not spend a week choosing. At 300 people per role the difference between
the best and worst enrichment vendor is tens of dollars and a few percentage
points of match rate. **Pick one, run 300 people through it, and change it if
the match rate is bad.** The waterfall exists so that changing is one line:

    [providers]
    enrich_waterfall = ["findymail", "apollo", "rocketreach"]

The real constraint is that this needs a person every working day.

## The four stages, and what to buy for each

### 1. Finding profiles

| Option | When it is right |
|---|---|
| **By hand, in the browser** | The senior seats. Head of Operations, Engineer, Controller. The SOP is explicit: reading each profile is the whole edge, and 300 people is two to three days of work. Set `providers.search = "manual"`. |
| **Apollo people search** | The volume seat, ops-generalist. It searches Apollo's own database, so no LinkedIn account is involved. Coverage of senior operators at 30 to 300 person companies is thinner than a hand built list, which is exactly why it is wrong for the senior seats. |
| **Apify actor** | Only if you find an actor that returns public profile data without a session cookie. Check that before paying. |
| **Sales Navigator Core** | Not an API. It is the browser tool you build the hand list in. Worth having for the filters. |

`outbound search <role>` prints the boolean string and the filter checklist
for the browser route, whichever provider is configured.

### 2. Finding the work email

Run a waterfall, cheapest and most accurate first. Adapters exist for
Findymail, Apollo and RocketReach.

What to check before you buy, in this order:

1. **Do they bill for unverified guesses?** Findymail's pitch is that it only
   charges for verified addresses. Confirm that is still true on their pricing
   page before you rely on it.
2. **Do they take a LinkedIn URL as input?** That is what we have. A vendor
   that needs a company domain is doing a worse job with less information.
3. **What is the match rate on your actual list?** Nobody's published number
   means anything. Run 50 people through a trial and count.
4. **Do they return personal addresses?** We do not want them. The Apollo
   adapter sets `reveal_personal_emails` to false and the RocketReach adapter
   drops anything typed as personal.

Clay is worth mentioning because the SOP names it. It is a waterfall of other
people's data plus a spreadsheet interface, and it costs more than the parts.
At 300 people it is not worth the setup time. At 3,000 it would be.

### 3. Verifying the address

Non-negotiable. A bounce rate above 3 percent damages a young sending domain,
and this domain has no reputation to spend.

Adapters exist for MillionVerifier and NeverBounce. Both are cheap per
thousand and both return a verdict this code maps to `valid`, `invalid`,
`risky` or `catch_all`. `invalid` is suppressed automatically. `risky` and
`catch_all` wait for a person, because at 300 people a person can decide.

Check the current price per thousand on the vendor's own pricing page. Do not
take a number from a comparison article.

### 4. Sending

| Option | When it is right |
|---|---|
| **Plain SMTP from the mailbox** | The founder sent seats. Fifteen to twenty a day, plain text, no tracking pixel, no sequencer footer. Deliverability comes from the low volume and from a person having written it. This is the default and it is what the SOP describes. |
| **Instantly or Smartlead** | The volume seat, or if you want built in warm up and reply detection. They add a sending reputation of their own and they handle warm up, which is real work. They also add a footprint: a sequencer's headers are recognisable. |

If you use a sequencer, still run `outbound replies sync`. This database is
what the report and the stage logic read.

### 5. Booking

Cal.com or Calendly. Adapters exist for both. What matters is not which one:

- Ten minutes, not fifteen.
- The four role questions on the form, **required**. `outbound questions
  <role>` prints them.
- An API that lets you read the answers and cancel a booking with a reason.
  Both do. Check which plan tier that needs before you buy, because on some
  plans the API is not included.

## Before you buy anything

1. Read the vendor's own current documentation. Not this file, and not a
   comparison article. Endpoints and prices move.
2. Check the terms for anything about scraping, cold email, or recruiting use.
3. Buy the smallest plan. Run 50 people through it. Count the match rate and
   the bounce rate yourself.
4. Then decide.

The adapters in `outbound/providers/` each name the environment variable they
need, and `tests/test_providers.py` asserts the request shape each one sends.
If a vendor changes their API, that test is where it will show up first.
