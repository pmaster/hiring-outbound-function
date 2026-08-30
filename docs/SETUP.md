# Setup

Do these in order. Steps 1 to 4 take a day of work and then ten days of
waiting, so start them before you build any list.

## 1. Decide who sends

The sender is not a detail. A senior operator answers a founder and deletes a
note from a coordinator. The SOP expects three to five times the reply rate on
a founder sent email.

| Role | Sender | Why |
|---|---|---|
| Head of Operations | Peter | Four failed attempts in two years. Do not delegate this one. |
| Engineer | Peter | Same reason, senior and rare. |
| Ops generalist | Recruiting | Volume seat. Four hires, a bigger list. |

Set `sender` in the role file. It is a label for people, not a switch.

## 2. The sending domain

**Decided (Peter, 2026-08-30): outbound sends from viewlineventures.com.** It
is the domain designated for full-time hiring, and it already sends job
notifications. `config/settings.toml` records the decision, so `outbound
doctor` does not keep asking.

The outbound SOP argued against sending from a domain that also carries normal
business email, because one complaint cluster can take that email down with
it. Peter weighed that and chose. Two things from the SOP's argument still
hold, so do them:

- Send from a **dedicated mailbox**, not one anyone relies on.
- Keep the volume low. The caps in `settings.toml` already are.

Whatever the domain, these two are hard-blocked by the code and must never
send FTE outreach: `cornerstonegigs.com` (the client and gig-worker domain,
and the name fails a bank compliance check) and `sunrunlabs.com` (the internal
corporate identity). Free mail providers are blocked too.

If you ever stand up a **separate** recruiting domain instead:

1. Register it at a **different registrar** from the live brands.
2. Turn on WHOIS privacy at the moment of registration. Adding it later does
   nothing, because the history is already captured.
3. Give the domain its own small careers page. Do **not** redirect it to the
   main site. A redirect re-links the new domain to the identity that is
   already burned.
4. Use a separate hosting account. If you use Cloudflare, use a separate
   Cloudflare account, because Cloudflare's own account graph links zones.
5. Pay with a card that is not linked to the live brands.

Full reasoning in `OPSEC.md`.

## 3. Create the mailboxes and the DNS records

Create two mailboxes on the new domain. Two is enough for 36 emails a day.

Set all three records. All three, not two:

| Record | Type | Value |
|---|---|---|
| SPF | TXT at the root | `v=spf1 include:<your mail provider> ~all` |
| DKIM | TXT at the selector your provider gives you | the key your provider gives you |
| DMARC | TXT at `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@<your domain>` |

Start DMARC at `p=none` and read the reports for two weeks. Move to
`p=quarantine` once the reports are clean.

Check your work before you send anything:

    dig +short TXT <your domain>
    dig +short TXT _dmarc.<your domain>

Then send yourself a real one and read it:

    python3 -m outbound send head-of-operations --test-to you@gmail.com --live
    python3 -m outbound send head-of-operations --test-to you@outlook.com --live

Open both and read the RAW headers. All three of SPF, DKIM and DMARC must say
pass. A DNS check says the records exist; only a delivered message proves the
mail is signed with them. Check it did not land in spam or promotions.

Do this again every time the copy changes and after any DNS change. The test
send bypasses the queue: nothing is recorded against a candidate, nothing
counts toward the daily cap.

## 4. Warm up

Warm both mailboxes for ten days before the first real send. At 18 a day you
do not need the 21 day ramp a bulk campaign needs.

Ramp: 5 a day for three days, 10 a day for three days, then 18.

`config/settings.toml` has `warmup.require_warmup_done = true`, which makes
`outbound doctor` remind you. When warm up is genuinely finished, send with
`--attest-warmup`.

## 5. Build the screener booking page

Ten minutes. Not fifteen.

Put the role's questions on the form as **required** questions:

    python3 -m outbound questions head-of-operations

Reviewing four answers each morning is much cheaper than cancelling a booked
call. Cancelling makes angry people and angry people write public complaints,
which is one plausible cause of the platform problems in `DECISIONS.md`.

Put the booking URL in `booking.screener_url`.

## 6. Build the job description pages

    python3 -m outbound pages

This writes `site/`: a careers index, one page per live role, and the
unsubscribe page. Self contained HTML, no external requests. Upload it to the
new domain.

The text is in `content/jd/*.md`. Edit it there and run the command again.

Do not soften the "what we are bad at" section. It is the most persuasive part
of the document to the only kind of candidate you want, and it filters out the
rest.

Every page is T1: a small trading firm in alternative assets, around fifty
people. No casino, no client model, no fund flow. A test enforces that on both
the pages and the emails.

Put each URL in `config/settings.toml`:

    [role_overrides.head-of-operations]
    jd_url = "https://<your domain>/roles/head-of-operations"

## 7. Build the unsubscribe route

CAN-SPAM requires a working unsubscribe route and a real postal address in
every commercial email. The code refuses to queue a message without both.

The cheapest route that actually works:

1. Put a form at `https://<your domain>/unsubscribe` that takes an email
   address and records it.
2. Set `identity.unsubscribe_url` to that URL. `{email_token}` in the URL is
   replaced with a stable per address token.
3. Export the form responses once a day and load them:

       python3 -m outbound suppress --from-file unsubscribes.csv

A reply saying "no thanks" is also an unsubscribe. Suppress it by hand:

    python3 -m outbound suppress someone@example.com --reason "asked to stop"

## 7b. If you send through a sequencer, make the campaign a passthrough

Skip this if you send over plain SMTP, which is the default and the right
choice for the founder sent seats.

A sequencer sends **its own** campaign copy, not the copy this repo renders.
If you paste a campaign body into Instantly, that is what candidates receive
and everything in `templates/` is ignored. Nothing errors.

So set the campaign's email body to exactly:

    {{outbound_body}}

and the subject line to:

    {{outbound_subject}}

The adapter pushes both as custom variables on each lead, and reads the
campaign back before the first send to check. It refuses rather than sending
the wrong copy. Turn the check off with
`providers.instantly.verify_campaign = false` only if you meant it.

## 8. Fill in the settings and check

    python3 -m outbound init
    # edit config/settings.toml
    python3 -m outbound doctor

`doctor` must exit clean before any live send. Then:

    python3 -m outbound doctor head-of-operations

That adds the per role checks: status, comp, and the job description URL.
