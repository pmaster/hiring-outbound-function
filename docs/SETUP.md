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

## 2. Register the sending domain

Do NOT send from `viewlineventures.com` or `sunbirdsystems.com`. One complaint
cluster blocklists the domain and kills normal business email. The code refuses
both.

1. Register one new domain at a **different registrar** from the live brands.
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

Then send one email to a seed address at Gmail and one at Outlook. Open the
raw headers. All three of SPF, DKIM and DMARC must say pass.

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

One page per live role, on the new domain. The email links to it. Use the
descriptions in the brain repo at `projects/sunbird/hiring-pack.md` Part 3 and
the pitch at `projects/sunbird/employee-pitch.md`.

Do not soften the "what we are bad at" section. It is the most persuasive part
of the document to the only kind of candidate you want, and it filters out the
rest.

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

## 8. Fill in the settings and check

    python3 -m outbound init
    # edit config/settings.toml
    python3 -m outbound doctor

`doctor` must exit clean before any live send. Then:

    python3 -m outbound doctor head-of-operations

That adds the per role checks: status, comp, and the job description URL.
