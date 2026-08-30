# Opsec

This applies `projects/sunbird/brand-opsec-sop.md` to outbound recruiting.
Read that first. This file only covers what changes when you send cold email.

## What this defends against

Competitor recon, ad platform and job platform linking, and casual OSINT. It
does not defend against a subpoena or a payment processor's file. Do not
confuse opsec with legal insulation.

## The four hard rules

1. **Never send FTE outreach from the client or internal domains.** Not
   `cornerstonegigs.com` (reserved for clients and gig workers, and the name
   fails a bank compliance check) and not `sunrunlabs.com` (the internal
   corporate identity). The code hard-blocks both, and the free mail providers
   too. The FTE hiring domain is `viewlineventures.com`, chosen by Peter on
   2026-08-30; sending from it is a deliberate decision, not a default (see
   `DECISIONS.md` and the code's `CONTESTED_SENDING_DOMAINS`).

2. **Never redirect the sending domain to the main site.** A redirect
   re-links the new domain to an identity that already has a problem, and it
   breaks the no cross links rule.

3. **Never connect a real LinkedIn account to a scraper.** Some tools run
   through a connected account or a pasted session cookie. LinkedIn restricts
   accounts for it. You already cannot afford to lose LinkedIn access. Read
   profiles in the browser and take email data from a vendor. The Apify
   adapter refuses an actor input that mentions a cookie unless someone sets
   `cookie_actor_ok = true` on purpose.

4. **Never let client acquisition and FTE hiring share a vector.** The Indeed
   ban has a stated cause: gig posting on ZipRecruiter. Gig posting is client
   acquisition. Hiring is a different funnel. Keep them on separate domains,
   separate cards, separate accounts, permanently.

## What must be separate

Every shared thing between two brands is a link. For the recruiting domain,
these must all be its own:

| Vector | What to do |
|---|---|
| Registrar | Different registrar from the live brands. |
| WHOIS | Privacy on at registration. Adding it later does nothing. |
| Hosting | Separate hosting account, its own IP. |
| Cloudflare | A separate Cloudflare account. Cloudflare's account graph links zones. |
| TLS | One certificate, one domain. Never a shared SAN. |
| Analytics and pixels | Its own property, or none at all. This is the single most trivial linker. |
| Payment | A card not used for the live brands. |
| Mailboxes | On the recruiting domain, with their own address pattern and signature. |
| Browser profile | A separate profile. Never log into two brands in one cookie jar. |
| Site copy | Written for this site. Not the main site with the name swapped. |

## Who is a link

Every person who touches two brands is a link. If one person builds every
site from one machine, the sites are separated and the builder is not. That is
usually the residual link, and it is the layer a subpoena targets anyway.

## Quarterly self audit

Try to connect the recruiting domain to the live brands the way a competitor
would.

- `crt.sh` for each domain. No shared SAN certificates.
- BuiltWith, PublicWWW and SpyOnWeb for each analytics and pixel ID. No ID on
  two sites.
- ViewDNS reverse IP and SecurityTrails. No shared IP or nameserver.
- whoxy WHOIS history. Privacy from day one, no shared registrant, no same
  day registration cluster.
- Reverse image search and copy paste search. No reused images or copy.
- By hand: could a person who found the recruiting site find a live brand in
  under an hour? If yes, find the shared vector and cut it.

Log the date and the result.

## What goes in an email

The step one email says "a trading firm in alternative assets" and "about
fifty people". It names no casino, no client model, no fund flow. That is the
T1 line from `projects/sunbird/employee-pitch.md`. Keep it there.

The rest of the story is for after the NDA. If a template edit crosses that
line, it is wrong.
