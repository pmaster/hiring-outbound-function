# Vendor APIs, verified

Every endpoint below was read off the vendor's own live documentation on
2026-08-30 by a research pass, then re-checked by a second adversarial pass
whose job was to delete anything it could not confirm. Confidence is marked
per endpoint: **high** means someone read it on the vendor's docs page that
session.

This exists because guessing an endpoint is the expensive kind of wrong. It
already caught four real bugs in the adapters:

- Findymail's path was `/api/search/linkedin`. There is no such endpoint;
  it is `/api/search/business-profile`.
- Apollo takes every parameter in the **query string**. A JSON body is a
  silent no-op, so the search was returning unfiltered results.
- Apify's `run-sync` route is cut off at 300 seconds, which any real
  sourcing run exceeds. The adapter now starts a run and polls.
- Cal.com's `cal-api-version` is **per endpoint**, not per API.

Re-run the research when an adapter starts failing. Vendors move.

---

## Apify

- **Category:** search
- **Base URL:** https://api.apify.com/v2
- **Docs:** https://docs.apify.com/api/v2

**Auth**

> Authorization: Bearer <APIFY_TOKEN> — CONFIRMED on
> https://docs.apify.com/api/v2. A query-param form `?token=<APIFY_TOKEN>` is
> also officially supported, and the docs explicitly call it less secure because
> "URLs are often stored in browser history and server logs". Use the header.
> Token is issued at Apify Console > Settings > API & Integrations
> (https://console.apify.com/settings/integrations).

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `POST` | `/v2/actors/{actorId}/run-sync-get-dataset-items` | Run an actor synchronously and get its default dataset items back in one call. Simplest path, but only safe for small/fast jobs (see notes). |
| high | `GET` | `/v2/actors/{actorId}/run-sync-get-dataset-items` | Run an actor synchronously with NO input (GET variant). |
| high | `POST` | `/v2/actors/{actorId}/runs` | Start an actor run asynchronously. This is the endpoint the recruiting pipeline should actually use. |
| high | `GET` | `/v2/actor-runs/{runId}` | Poll a run's status (and optionally long-poll until it finishes). |
| high | `GET` | `/v2/datasets/{datasetId}/items` | Fetch the result items from a dataset by dataset id. |
| high | `GET` | `/v2/actor-runs/{runId}/dataset/items` | Shortcut: fetch a run's default dataset items directly from the run id, skipping the defaultDatasetId lookup. |
| high | `GET` | `/v2/actors/{actorId}/runs/last/dataset/items` | Fetch the LAST run's dataset items for an actor. |
| high | `POST` | `/v2/actor-runs/{runId}/abort` | Abort a running actor run (kill switch for a runaway or misconfigured job). |

**Rate limits**

> CONFIRMED against https://docs.apify.com/api/v2, two layers. GLOBAL: 250,000
> requests per minute — counted per user for authenticated requests, per IP
> address for unauthenticated ones. PER-RESOURCE (default): 60 requests per
> second per resource (a single actor, dataset, key-value store, etc.). PER-
> RESOURCE (elevated): 200 req/s for key-value store record CRUD; 400 req/s for
> Run Actor, Run Actor task, Metamorph, Push items to dataset, and request-queue
> operations. Over-limit returns HTTP 429 Too Many Requests. BACKOFF SPEC
> REFINED — the docs are more specific than the original report's generic
> "double the wait": start with a ~500ms delay, wait a RANDOM interval between
> the current delay and double it, then retry; after each failure double the
> maximum delay for the next attempt (randomized exponential backoff, not fixed
> doubling). The official JavaScript and Python clients implement this
> automatically. None of these limits is a real constraint at 300-2000 people
> per role; the actor's own scrape rate and the 300s sync ceiling are what bind.

**Pricing**

> All actor prices below were RE-CHECKED live this session against each actor's
> own Apify Store page. All eight figures from the original report were
> confirmed unchanged — no stale pricing found.  APIFY PLATFORM (subscription,
> separate from actor charges): free tier plus paid monthly plans; the LinkedIn
> actors relevant here are almost all "pay per event" or "pay per result", where
> the actor price is fixed and platform compute is NOT additionally billed
> (harvestapi states "You are not charged for the Apify platform usage, but only
> a fixed price for specific events"). Monthly-rental actors are the exception —
> those bill rental + platform usage on top, and the rental "is subtracted from
> your prepaid usage every month after the free trial period".  PER-ACTOR
> (confirmed): - harvestapi/linkedin-profile-search — pay per event. Short mode:
> "$0.10 per search page" (25 profiles/page). Full mode: "$0.10 per search page
> + $0.004 per each full profile scraped". Full + email search: "$0.10 per
> search page + $0.01 per each full profile scraped with email search". Worked
> cost for 1,000 full profiles: 40 pages x $0.10 = $4.00, plus 1,000 x $0.004 =
> $4.00 → ~$8.00/1k. With email search: $4.00 + $10.00 → ~$14.00/1k. Source:
> https://apify.com/harvestapi/linkedin-profile-search. - harvestapi/linkedin-
> profile-scraper — "$4 per 1000 detailed profiles" (profile details, no email);
> "$10 per 1000 profiles with email address search". Source:
> https://apify.com/harvestapi/linkedin-profile-scraper. - apimaestro/linkedin-

**Gotchas**

- ADVERSARIAL REVIEW RESULT: all 8 endpoints in the original report were opened against live Apify reference pages and all 8 EXIST. Nothing was invented. Three material corrections were made — one wrong path, one wrong status-code hedge, one wrong ToS finding — plus several param-list completions. Each is flagged in the entry it affects and summarized in the gotchas below.
- CORRECTION 1 (WRONG PATH — would have 404'd in code). Last-run dataset items is /v2/actors/{actorId}/runs/last/dataset/items, NOT /v2/acts/{actorId}/runs/last/dataset/items as the original report reconstructed. The report itself admitted it had not opened the reference page; I did (https://docs.apify.com/api/v2/actor-runs-last-dataset-items- get) and the path uses /actors/. Confidence raised medium -> high. This is exactly the class of guessed-path error that gets written into an adapter and fails at runtime.
- CORRECTION 2 (WRONG HEDGE). The original report said the per-endpoint reference page lists only 201/400/401/402/403 and so 408 should be treated as 'possible-but-not-guaranteed'. The reference page in fact states outright: 'If the Actor run exceeds 300 seconds, the HTTP response will return the 408 status code (Request Timeout).' Treat 408 as the documented overrun signal and branch on it — but still handle a dropped connection separately, since the same page warns an idle HTTP connection may not survive and 'if the connection breaks, you will not receive any information about the run and its status.'
- CORRECTION 3 (WRONG ToS FINDING). The original report flagged bebity/linkedin-premium-actor as cookie-posture 'unresolved — treat as unsafe'. Its documented input schema contains no cookie, credential or session field at all (only action, keywords, limit, location, profileFields). It is documented cookie-free. It still is not recommended, but for cost/model reasons ($29/month rental + platform usage, thin input schema), not ban risk. Do not repeat the 'silence is not a no' framing for this actor.
- CORRECTION 4 (SOFTENED CLAIM). The original report asserted '/v2/acts/ is DEPRECATED but still fully functional' as though quoting the docs. No Apify reference page I opened states a deprecation. What IS true and verifiable: every current reference page renders the /v2/actors/ and /v2/actor-runs/ forms, and /v2/acts/ survives only as a legacy alias in older SDK examples and third-party snippets. Operational advice is unchanged — write /v2/actors/ — but do not cite a deprecation notice that is not there.
- CORRECTION 5 (INCOMPLETE PARAM LISTS). Both sync and async param lists in the original report were missing documented params. run-sync-get-dataset- items also accepts restartOnError, simplified, skipFailedPages, feedTitle, feedDescription. POST /runs also accepts restartOnError. Get dataset items also accepts simplified, feedTitle, feedDescription. Corrected in each endpoint entry.
- CORRECTION 6 (OVERSTATED HEDGE ON PRICING). All eight actor prices were re- read live and none had drifted. One wording fix: supreme_coder/linkedin- profile-scraper is listed at a flat '$5.00 / 1,000', not 'from $5.00 / 1,000'.
- THE 300-SECOND SYNC CEILING IS THE MAIN ARCHITECTURAL CONSTRAINT. run-sync- get-dataset-items must finish in 300s or return 408. A 300-2000 person LinkedIn search will not. Build the adapter on the async path — POST /v2/actors/{id}/runs, then long-poll GET /v2/actor- runs/{runId}?waitForFinish=60, then page GET /v2/actor- runs/{runId}/dataset/items. Keep run-sync only for tiny probes (<=25 profiles) and smoke tests.
- ACTOR ID USES A TILDE, NOT A SLASH: `harvestapi~linkedin-profile-search`. Confirmed docs wording: 'The username of the Actor owner plus the Actor name, separated by a tilde (~). For example, `apify~instagram-scraper`.' Hex actor IDs also work. A slash will route wrong — always send the tilde.
- RUN STATUS LIVES AT A DIFFERENT ROOT THAN RUN CREATION. Create at /v2/actors/{actorId}/runs; poll at /v2/actor-runs/{runId}. There is no /v2/actors/{actorId}/runs/{runId} in the flow you want. Confirmed on both reference pages. This is the single easiest path to get wrong.
- waitForFinish IS THE ONLY QUERY PARAM ON GET /v2/actor-runs/{runId}. Max value 60, default 0, confirmed verbatim. Do not invent filters on this endpoint.
- RESPONSE ENVELOPE IS INCONSISTENT — CONFIRMED ON BOTH SIDES. Run objects come wrapped as {"data": {...}}. Dataset items come back as a BARE ARRAY with no wrapper (the sync endpoint's own docs show `[{ "myValue": "some value" }]`). Do not write one generic unwrapper for both.
- ALWAYS SET maxItems AND maxTotalChargeUsd ON THE RUN CALL. Both confirmed as accepted query params on POST /runs and on run-sync. They are the only hard spend caps on pay-per-result actors. A misconfigured ICP filter that matches half of LinkedIn is otherwise billable in full.
- PAGINATE DATASET READS. All four X-Apify-Pagination-* headers confirmed on both the dataset-items and run-sync reference pages. Read X-Apify- Pagination-Total and loop on offset/limit; do not assume one GET returns everything at 2000 rows. Use format=jsonl for streaming rather than buffering a large json array.

**Terms and account risk**

> THE COOKIE QUESTION — re-verified on every store page this session. One
> finding changed.  REQUIRE YOUR OWN LinkedIn session cookie (direct account-ban
> risk — do not use): - curious_coder/linkedin-people-search-scraper. CONFIRMED
> verbatim: "This actor works on a logged in linkedin account, but doesn't
> require login details or 2FA as it does't login but uses already generated
> linkedin session information." Users must "pass linkedin cookies to this actor
> to use the existing session to access search results page and perform
> scraping." Setup is a Cookie-Editor browser export pasted into the input
> field. That "no login details needed!" framing is misleading — handing over
> `li_at` IS handing over the account. Detection lands on the cookie's owner,
> not on Apify. - logical_scrapers/linkedin-people-search-scraper. CONFIRMED
> verbatim: "Required cookies: li_at, JSESSIONID. Export from browser dev tools
> > Application > Cookies." Also "You must provide valid LinkedIn session
> cookies from a logged-in account", and the page notes cookies expire and need

**Verdict**

> RECOMMEND Apify as the sourcing layer. The original report survives
> adversarial review largely intact — every endpoint it listed is real and every
> price it quoted is current — but it contained one wrong path that would have
> failed at runtime, one incorrect status-code hedge, and one incorrect ToS
> finding. All three are corrected above.  Use: harvestapi~linkedin-profile-
> search for ICP search (cookie-free, structured LinkedIn-native filters that
> map cleanly onto a role ICP, ~$8 per 1,000 full profiles), and optionally
> harvestapi~linkedin-profile-scraper for deep detail on a shortlist by URL
> ($4/1k, $10/1k with email search). apimaestro~linkedin-profile-search-scraper
> at $5/1k is a reasonable cookie-free second source for redundancy, but its
> input schema is confirmed thin (firstname, lastname, location,
> current_job_title, max_profiles, include_email) — too coarse for a real ICP,
> so treat it as a fallback, not the primary.  Avoid: curious_coder~linkedin-
> people-search-scraper and logical_scrapers~linkedin-people-search-scraper.
> Both require you to paste your own li_at session cookie, re-confirmed verbatim
> on both pages this session. That is a direct account-ban risk with no upside —
> the cookie-free actors cover the same search surface at lower cost without
> putting a LinkedIn account on the line. bebity~linkedin-premium-actor is NOT a
> cookie risk (its documented input schema has no credential field at all — the
> original report was wrong to flag it as unresolved), but skip it anyway:
> $29/month rental plus platform usage for a thinner schema than harvestapi.  On
> the API itself: stable, well documented, a clean fit, and it matches its docs

---

## Apollo.io

- **Category:** enrich
- **Base URL:** https://api.apollo.io/api/v1
- **Docs:** https://docs.apollo.io/reference/apollo-api  (machine-readable spec: https://docs.apollo.io/openapi/apollo-rest-api.json — VERIFIED this session: HTTP 200, 1,109,870 bytes, OpenAPI 3.1.0, servers[0].url = https://api.apollo.io/api/v1, exactly 74 paths. Downloaded and parsed programmatically, not skimmed. People-search reference page: https://docs.apollo.io/reference/people-api-search — VERIFIED live. Credit table: https://docs.apollo.io/docs/api-pricing — VERIFIED. Rate limits: https://docs.apollo.io/reference/rate-limits — VERIFIED. Guide: https://docs.apollo.io/docs/find-people-using-filters — VERIFIED, shows POST https://api.apollo.io/api/v1/mixed_people/api_search.)

**Auth**

> x-api-key: <key>  (VERIFIED against components.securitySchemes in the live
> spec: {"apiKey": {"type":"apiKey","in":"header","name":"x-api-key"}}. Header
> names are case-insensitive in HTTP, so X-Api-Key also works.) Alternative for
> partners only: Authorization: Bearer <OAuth2 JWT> (securitySchemes.bearerAuth,
> http/bearer/JWT). Global security is [{apiKey:[]},{bearerAuth:[]}]; no
> operation overrides it. VERIFIED: there is NO api_key query or body parameter
> anywhere in the spec — a programmatic scan of all 74 paths and every
> operation's parameters found zero parameter whose name contains "api_key".
> That form is legacy and undocumented today.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `POST` | `/api/v1/mixed_people/api_search` | People search (net-new prospects) — the ICP search step. CONFIRMED: the path in the original brief, /mixed_people/search, does NOT exist. It is absent |
| high | `POST` | `/api/v1/people/match` | People match / enrichment — the email reveal step. One person per call. |
| high | `POST` | `/api/v1/people/bulk_match` | Bulk people match / enrichment — use THIS for volume, not /people/match. Up to 10 people per call. |
| high | `GET` | `/api/v1/people/{id}` | Get complete person info by Apollo id. LISTED SO YOU AVOID IT — it looks like the cheap way to fetch a person and is a trap. Every claim below is quot |
| high | `POST` | `/api/v1/usage_stats/credit_usage_stats` | Read live credit balances by credit type — run this before and after each role's run to police spend. |
| high | `POST` | `/api/v1/usage_stats/api_usage_stats` | Read your actual rate limits and current usage per endpoint — authoritative over the published table, especially on legacy plans. |
| high | `POST` | `/api/v1/mixed_companies/search` | Organization / company search — if you want to build the company list first and then search people within it. |

**Rate limits**

> From https://docs.apollo.io/reference/rate-limits — re-fetched and re-verified
> this session. All figures below matched the original report exactly; nothing
> was stale.  Default per-plan limits:   Free:          50/min,   200/hr,
> 600/day   Basic:        200/min,   400/hr,  2,000/day   Professional: 200/min,
> 400/hr,  2,000/day   Organization: 200/min,   600/hr,  6,000/day  Enrichment
> endpoints (people/organization/job-posting enrichment) get RAISED limits:
> Free:      50 req/min (20 for bulk), 200/hr (100 bulk), 600/day   Basic /
> Professional / Organization: 1,000 req/min, NO hourly limit, NO daily limit
> Search endpoints (people/organization/news search):   Free:      50/min,
> 200/hr, 600/day   Basic / Professional / Organization: 200/min, 6,000/hr,
> 50,000/day  Note that the doc names Basic, Professional and Organization
> individually in all three tables — see the pricing field for why that matters
> to the plan-access question.  Tighter special cases: query analytics reports 5
> requests per hour; export conversations on Free 1 request per minute and 20

**Pricing**

> VENDOR-OFFICIAL PRICE TABLE STILL COULD NOT BE READ.
> https://www.apollo.io/pricing renders its plan table from a client-side data
> fetch; the page text contains feature-row labels and policy prose but NO price
> or credit numbers. Confirmed again this session: "Specific plan prices per
> user per month and credit allocations are not listed on this page." Treat the
> figures below as third-party and re-confirm in-app before committing.  Vendor
> statements I DID read on apollo.io/pricing (verbatim, re-confirmed this
> session): - "We also offer API Access on our Custom plans for more advanced
> integrations." - "The plans shown on this page are permitted for internal
> business use only. Use of these plans to power external products, share data
> with customers, or resell Apollo data is not allowed under our standard
> terms." - "You consume export credits whenever you export a contact outside of
> Apollo. For example, when you use CSV, CRM, or Person API enrichment and sync
> the data to any system outside Apollo, like Outreach or Salesloft."  PLAN-
> ACCESS CONTRADICTION — NARROWED, not resolved. The original report called this
> "genuinely unresolved". New evidence tilts it toward API access being
> available on ordinary paid plans: - https://docs.apollo.io/reference/rate-
> limits publishes API rate limits BY PLAN NAME for Free, Basic, Professional
> and Organization. Apollo would not publish per-endpoint API limits for Basic
> and Professional if those plans had no API. - The API overview says "Most

**Gotchas**

- VERIFICATION SUMMARY — WHAT CHANGED. I downloaded the OpenAPI spec (1,109,870 bytes) and parsed it programmatically rather than reading prose, then cross-checked the live doc pages. All seven endpoints in the original report EXIST with the exact method and path claimed; none were invented and none needed deleting. Confirmed exactly: 74 paths, servers[0].url, both securitySchemes, no api_key parameter anywhere, the query-param-on-POST shape, the bulk_match split shape, the redacted search response, the email_not_unlocked placeholder matrix, the three-value email_status, all credit costs, all rate-limit tables, all four error-body shapes, and both ToS quotes. Six things were wrong or incomplete and are corrected in the entries above: the /people/match response shape, the bulk_match response shape, has_direct_phone's type, the mixed_companies/search response shape, the person_seniorities en
- CORRECTED — /people/match DOES NOT RETURN A `waterfall` FIELD. The original report gave its responseShape as '{ request_id, waterfall, person: {...} }'. The 200 schema has exactly two top-level properties, request_id and person, and the vendor's worked example shows only those. `waterfall` exists on /people/bulk_match, not here. If you coded a waterfall check against /people/match you would read undefined forever.
- CORRECTED AND EXPANDED — bulk_match returns much more than an array. The array key is `matches`, and alongside it the response carries request_id, status, error_code, error_message, total_requested_enrichments, unique_enriched_records, missing_records, credits_consumed, waterfall and phone_enrichment. The original report named none of these. `credits_consumed` is the useful one: it gives you per-call spend inline, so you can enforce a budget without polling credit_usage_stats between batches. missing_records and unique_enriched_records give you reconciliation counts for free.
- CORRECTED — bulk_match items are NOT the same object as /people/match's person. They differ on identity fields: matches[] carries account_id and account; person carries contact_id and contact. The other 27 fields line up. A shared parser must handle both key pairs, and code that looks for contact_id as the 'is this already my contact' signal will always miss on bulk_match output.
- CORRECTED — has_direct_phone IS A STRING, NOT A BOOLEAN. In the vendor's own api_search example it returns "Yes" while has_email returns true on the same object. The original report described the whole set as 'availability BOOLEANS'. `if (p.has_direct_phone === true)` silently never fires. The other has_* fields on both the person and the organization are genuine booleans — this one field is the exception.
- CORRECTED — mixed_companies/search response shape, and it is BETTER than the original report implied. Top level is { breadcrumbs, partial_results_only, has_join, disable_eu_prospecting, partial_results_limit, pagination, accounts, organizations, model_ids, num_fetch_result, derived_params }. Crucially, unlike people search this response is NOT redacted: each organizations[] record carries real primary_domain, website_url, linkedin_url, founded_year, phone and more. So company search is the one search surface that hands you usable data — at 1 credit per page. Also watch partial_results_only and disable_eu_prospecting, which flag silently truncated result sets.
- CORRECTED — person_seniorities[] has no machine-readable enum. The original report presented the eleven values as coming from the spec's enum. The schema is a bare {type: array, items: {type: string}}; the values live only in the description prose. Anything you generate from the spec will accept a typo'd seniority and return silently wrong results. Hardcode the list and test it against live responses.
- CORRECTED — the people-search docs URL. The original report correctly noted that https://docs.apollo.io/reference/people-search returns 404 (re- confirmed this session), but never gave the working one. It is https://docs.apollo.io/reference/people-api-search. Apollo's how-to guide at https://docs.apollo.io/docs/find-people-using-filters also shows 'POST https://api.apollo.io/api/v1/mixed_people/api_search', so the vendor's own guides are consistent — there is no stale internal reference to the old path.
- DOWNGRADED — the Clay community deprecation citation is unverifiable. The original report cited a Clay community thread titled 'Apollo API Endpoint Deprecation: Use New api_search' (Dec 2025) as corroboration. The thread title does appear in search results, but the page itself returns only Clay's navigation shell with no post content, so I could not read what it says. Drop it as evidence. The finding does not need it: /mixed_people/search is absent from a programmatic scan of all 74 spec paths and its reference page 404s, while /mixed_people/api_search is present in the spec, has a live reference page, and appears in Apollo's own how-to guide. Hardcode api_search.
- UNVERIFIED — the 'unified credit plan' warning. The original report attributed to the credit_usage_stats docs a warning that on a unified credit plan lead_credit is a shared pool whose left_over already nets out mobile reveals, exports and dialer minutes. I could not find that text in the endpoint description. I have not disproved it, but do not rely on the quote. The safe behaviour is unchanged: read lead_credit specifically, never sum the credit types.
- NEW — api_usage_stats has NO response schema, only an example, and its keys are weird. The 200 response object in the spec carries no schema at all, so codegen gives you nothing. Its keys are literal strings containing a JSON- encoded two-element array: to find your people-search limit you must match the key `["api/v1/mixed_people", "api_search"]` exactly, brackets, quotes, comma and space included. You cannot index by path. Also, in the vendor's own example left_over equals limit even where consumed is non-zero — compute limit minus consumed yourself rather than trusting left_over.
- NEW — the scope string for GET /people/{id} is not its path. Provisioning uses the internal name `api/v1/people/show` (OAuth scope person_read), not `api/v1/people/{id}`. If you ever do need that endpoint and provision by REST path, the key will 403.
- SEARCH FILTERS ARE QUERY PARAMS ON A POST — CONFIRMED. /mixed_people/api_search has no requestBody key in the spec and all 23 parameters are in='query'. Same for /mixed_companies/search (24 params, all query). If your adapter posts a JSON body it returns unfiltered results and looks like it works. Build the URL, not the body. Arrays repeat with a literal [] suffix: person_titles[]=a&person_titles[]=b.
- SEARCH RETURNS ALMOST NOTHING USABLE — CONFIRMED against the schema and the vendor's example. Eleven person fields, nine org fields, and that is all: no email, no linkedin_url, no last name (last_name_obfuscated = 'Hu***n'), no city/state/country values, no company domain. The only field you can act on is people[].id. Design the pipeline as api_search -> collect ids -> bulk_match in batches of 10. Do not plan on getting a LinkedIn URL out of search; only enrichment returns one.

**Terms and account risk**

> 1. INTERNAL BUSINESS USE ONLY. Verbatim from apollo.io/pricing, re-confirmed
> this session: "The plans shown on this page are permitted for internal
> business use only. Use of these plans to power external products, share data
> with customers, or resell Apollo data is not allowed under our standard terms.
> These use cases require a separate agreement with custom pricing and terms."
> Recruiting for your OWN company is internal use and fine. Running this for
> client roles and handing candidate data to the client is outside standard
> terms and needs a separate agreement. This is the single biggest contractual
> risk in the design.  2. NO LINKEDIN SCRAPING IS INVOLVED, and that is a point
> in Apollo's favour. Apollo is a static database queried by API. The "find
> LinkedIn profiles" pipeline step is satisfied by mixed_people/api_search plus
> bulk_match — bulk_match RETURNS linkedin_url on the enriched record (verified:
> it is in the matches[] property list) and /people/match ACCEPTS linkedin_url
> as a match input (verified: it is a documented query parameter). Nothing

**Verdict**

> RECOMMEND, with three conditions. The original report survives adversarial
> checking better than most: I downloaded and programmatically parsed the 1.1 MB
> OpenAPI spec rather than reading prose, and all seven endpoints exist with
> exactly the method and path claimed. Nothing was invented, nothing needed
> deleting, and no endpoint needed a confidence downgrade. Six response-shape
> and provenance details were wrong and are corrected above — the two that would
> actually break code are that /people/match returns no `waterfall` field, and
> that has_direct_phone is the string "Yes" rather than a boolean.  Apollo is
> the right enrichment layer for this pipeline. The API is real, current, and
> fully specified in a machine-readable OpenAPI 3.1 document the vendor
> publishes and keeps consistent with its own guides. The economics fit: people
> search is 0 credits, enrichment is 1 credit per work email found and 0 per
> miss, so a 2000-person role costs about 2000 lead credits with no charge for
> the ICP exploration that precedes it. Rate limits are irrelevant at your
> volume — paid enrichment is 1,000 req/min with no hourly or daily cap, and
> 2000 people is 200 bulk calls, about a minute of allowance. Crucially for
> account safety, Apollo never touches LinkedIn: it is a database lookup that
> both accepts and returns linkedin_url, so nothing in the enrichment path can
> get an account banned.  Condition 1: do not treat Apollo's email_status as
> verification. Three values, and 'extrapolated' means pattern-guessed. Apollo
> now says outright that the field describes the address it holds internally and
> should be used "to judge deliverability once you have a real address, not to

---

## RocketReach

- **Category:** enrich
- **Base URL:** https://api.rocketreach.co/api/v2
- **Docs:** https://docs.rocketreach.co/reference/rocketreach-api  (machine-readable page index: https://docs.rocketreach.co/llms.txt — every page below has a .md variant that returns the raw OpenAPI-derived content, which is the best source to build against)

**Auth**

> Api-Key: <YOUR API KEY>  (HTTP request header). CONFIRMED on people-lookup-
> api. OpenAPI security scheme is an apiKey in: header, name: Api-Key. The docs
> security note states verbatim: "Older clients may use an `api_key` query
> parameter, but this behavior is deprecated." Do not use the query parameter.
> NOTE: several vendor curl examples (person/search, universal/person/search)
> omit the Api-Key header entirely — that is a docs omission, not an anonymous
> endpoint.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `GET` | `/person/lookup` | Person enrichment / lookup — the core call. Returns a profile with emails and phones. Asynchronous: may return before contact data is ready. |
| high | `GET` | `/person/checkStatus` | Poll for completion of one or more in-flight person lookups. The answer to the async "searching" status. |
| medium | `POST` | `/person/search` | Person search by ICP criteria. Returns candidate profiles WITHOUT contact info; you then call /person/lookup per profile id. |
| high | `GET` | `/profile-company/lookup` | Combined person + company enrichment in one call. Returns the profile plus compiled company data. |
| high | `POST` | `/bulkLookup` | Bulk person enrichment, 10-100 profiles per request. Webhook-delivered only. |
| high | `GET` | `/account/` | Account status: plan state, credit balances, and current rate-limit consumption. Use for pre-flight quota checks. |
| high | `GET` | `/universal/person/lookup` | Universal (credit-metered) person lookup. Alternative billing model where you explicitly opt into which data you pay to reveal. |
| high | `POST` | `/universal/person/search` | Universal person search (credit-metered variant of /person/search). |
| high | `GET` | `/universal/person/check_status` | Poll completion for Universal person lookups. |

**Rate limits**

> CORRECTED — THE PRIOR REPORT OMITTED THE HOURLY, DAILY AND MONTHLY CAPS
> ENTIRELY AND ITS THROUGHPUT CONCLUSION WAS WRONG. Source:
> https://docs.rocketreach.co/reference/rate-limits, read this session.  Global
> ceiling (verbatim): "there is a global rate limit of 10 requests per second
> across all APIs." Exceeding any limit returns HTTP 429 "Too Many Requests"
> with a Retry-After header giving "the number of seconds to wait until the
> endpoint becomes available again." The official Python SDK reads
> response.headers["retry-after"] and falls back to 2 seconds if absent. No
> remaining-quota response header is documented — use GET /account/ (rate_limits
> array: action, duration, limit, used, remaining) for that.  FULL DOCUMENTED
> TABLE (Minute / Hourly / Daily / Monthly):  Person Lookup — the binding
> constraint for this pipeline: - Essentials: 15 / 100 / 500 / 5,000 - Pro:
> 50 / 300 / 1,500 / 20,000 - Ultimate:  100 / 1,000 / 3,000 / 50,000 - Custom:
> 250 / 2,500 / 10,000 / 200,000  Person Search: - Essentials: 15 / 50 / 500 /

**Pricing**

> CREDIT CONSUMPTION — re-confirmed verbatim this session
> (https://docs.rocketreach.co/reference/universal-credits-overview): - Person
> Search: 1 credit / page of results (up to 100 results per page) - Company
> Search: 2 credits / page of results (up to 100 results per page) -
> Professional Email: 2 credits / person profile, with verified (A or A-) emails
> - Personal Email: 3 credits / person profile, with verified (A or A-) emails -
> Phone: 6 credits / person profile with phones - Detailed Person Enrichment
> (Job History, Education, Skills, Social Links): 1 credit / person profile -
> Healthcare Enrichment (NPI #, License #, Specialization, Credentials): 1
> credit / person profile - Company Enrichment (Revenue, Employee Size, Industry
> Keywords): 1 credit / company profile  CLASSIC (non-Universal) BILLING — re-
> confirmed (docs FAQ and MCP Tools Reference): - person_search /
> company_search: "No credits consumed." - person_lookup: "Consumes 1 lookup
> credit, plus 1 person export credit" - Premium Credit = charged when "A or A-
> grade email or valid phone" is returned - Standard Credit = charged when "A or
> A- grade email only" is returned - "Lookups: No credit is charged if no data
> is found" - NEW, CONFIRMED THIS SESSION: "B or F grade emails: No credits are
> charged." This is a double finding — it proves B and F grades exist on the
> email ladder (the prior report said it could not confirm the ladder), and it
> means low-grade results are free, so aggressive retry and wide-net lookups

**Gotchas**

- CHANGED IN REVIEW — RATE LIMITS WERE WRONG AND THE ERROR WAS MATERIAL. The prior report listed only per-minute limits, said "No burst limits documented", and concluded "Rate limiting is not the bottleneck." The docs publish Minute/Hourly/Daily/Monthly caps for every endpoint. Person Lookup on Essentials is 15/min but only 100/hour and 500/day, so 2,000 lookups takes ~4 calendar days, not the ~2.2 hours claimed. On Pro it is ~2 days. Only Ultimate and Custom finish a 2,000-person run inside one day. Size your tier off the DAILY cap and make the run checkpointed and resumable across days.
- CHANGED IN REVIEW — /person/search RESPONSE ENVELOPE IS CONTESTED ON VENDOR PROPERTY, CONFIDENCE DOWNGRADED TO MEDIUM. The People Search API reference page's own OpenAPI schema declares the body as a bare top-level ARRAY of ProfileSearchResultSerializerBase with no wrapper. The MCP Tools Reference page shows {"pagination":{"start":1,"next":11,"total":4242},"profiles":[...]} and the official Python SDK reads ['profiles'] and ['pagination']['next']. The prior report presented the envelope form as "confirmed twice" and did not disclose the contradiction. Write a parser that accepts both: if the body is a list use it directly and paginate start += page_size; if it is a dict read ['profiles'] and paginate on ['pagination']['next'].
- CHANGED IN REVIEW — THE PRIOR REPORT'S /person/search CURL EXAMPLE WAS NOT THE DOCS EXAMPLE. It showed a rich query with name, current_title, current_employer, location, skills, page_size and start presented as vendor- verbatim. The actual docs example is: --data '{"query":{"keyword":["Marc Benioff"]},"order_by":"popularity"}'. The wider PersonQuery facet list, the '-' negation prefix, the '::~' location radius syntax and the "80+ facets" claim are UNCONFIRMED. Probe each facet you intend to depend on against a live key before building ICP filters on it.
- CHANGED IN REVIEW — "V1 IS DEAD" IS UNCONFIRMED, DOWNGRADED. The prior report asserted "RocketReach has fully migrated to v2; a v1 endpoint always returns an error." No current docs page states this and there is no v1 page in the docs index (https://docs.rocketreach.co/llms.txt). The official Python SDK still carries a live v1 route table: {1: {'lookup': 'lookupProfile', 'check_status': 'checkStatus', 'search': 'search'}}. Accurate statement: v1 is absent from current documentation and should be treated as unsupported for new work, but the claim that it hard-errors is unverified. Build on v2 regardless.
- CHANGED IN REVIEW — ADDED A CONFIRMED ENDPOINT THE PRIOR REPORT MISSED: GET /api/v2/profile-company/lookup ("People and Company Lookup API"), which returns profile plus compiled company data in one call. Useful if ICP scoring needs employer firmographics alongside the contact. Its credit treatment is undocumented — verify before making it the default path.
- CHANGED IN REVIEW — /account/ IS BETTER DOCUMENTED THAN REPORTED. The prior report said it could not confirm fields beyond credit_usage and rate_limits. The full UserModel is published: id, first_name, last_name, email, state (enum anonymous|test_user|registered), credit_usage[] of {credit_type, allocated, used, remaining}, and rate_limits[] of {action, duration, limit, used, remaining}. credit_usage[].credit_type is what distinguishes lookup credits from export credits at runtime, and rate_limits[].duration is how you read the minute vs hourly vs daily bucket. Both are load-bearing for a pre-flight check now that daily caps are known to bind.
- CHANGED IN REVIEW — EMAIL GRADES B AND F ARE CONFIRMED TO EXIST, AND ARE FREE. The prior report said it could not find any page enumerating the email grade ladder. The FAQ states "B or F grade emails: No credits are charged." So the email ladder includes at least A, A-, B and F. Still do not hardcode a closed set — filter with a string membership test against {"A", "A-"} and treat everything else as needing your external verifier. The billing consequence is favourable: low-grade results cost nothing, so a wide net and aggressive retries are free.
- CHANGED IN REVIEW — phones[] HAS MORE FIELDS THAN REPORTED, THREE OF THEM DEPRECATED. Confirmed full list: number, e164, country_code, extension, type, grade, recommended, plus validity (DEPRECATED), premium (DEPRECATED) and last_checked (DEPRECATED). The prior report listed only five and omitted the deprecation markers. Do not build on validity, premium or last_checked.
- CHANGED IN REVIEW — lookup_type ENUM HAS EXACTLY SIX VALUES: standard, premium, "premium (feeds disabled)", bulk, phone, enrich. The prior report appended "" and null, which are not in the documented enum.
- CHANGED IN REVIEW — bulkLookup's webhook_id IS OPTIONAL IN THE SCHEMA, NOT REQUIRED. The real constraint is "This endpoint requires for at least one webhook URL enabled for this endpoint, or a webhook ID specified." A webhook configured on the account satisfies it without passing webhook_id.
- CHANGED IN REVIEW — THE ToS TRANSFER BAN IS QUALIFIED BY CONSENT. "you may not transfer or disclose the Lookup Information to anyone else" is conditioned on absence of prior written consent from RocketReach. The prior report stated it as absolute. If you need to hand enriched data to a client, asking for written consent is an available route, not a dead end.
- VENDOR CURL EXAMPLES ARE UNRELIABLE — CHECK THEM AGAINST THE SCHEMA BLOCK. The People Lookup Status page prints a curl example for a different endpoint with a malformed base path: POST https://api.rocketreach.co/v2/api/search (note /v2/api/ reversed versus the correct /api/v2/). The person/search and universal/person/search examples both omit the required Api-Key header. Copying any of these verbatim produces a broken call.
- ASYNC IS THE DEFAULT, NOT AN EDGE CASE. GET /person/lookup returns HTTP 200 immediately with a status that may be "searching", "progress", "waiting" or "not queued". Docs verbatim: "A status other than 'complete' indicates the lookup is not finished, and the contact info is not fully available yet." Treat a 200 as a job receipt, not a result; do not write emails to the pipeline until status == "complete".
- STATUS VALUES DIFFER BETWEEN DOCS PAGES — CONFIRMED, AND IT IS SYSTEMATIC. /person/lookup and /universal/person/check_status document four values (complete, progress, searching, not queued); /person/checkStatus documents five (complete, failed, waiting, searching, progress). Code against the union of all six. Terminal-success is "complete" only; terminal-failure is "failed". Never use an exhaustive enum match that raises on an unknown value.

**Terms and account risk**

> Re-read verbatim from https://rocketreach.co/terms this session. The substance
> of the prior assessment holds, with two wording corrections.  EXPLICITLY
> PERMITTED, and this is the important one — CONFIRMED VERBATIM: "only use
> Lookup Information to identify prospective sales opportunities, identify
> candidates for recruitment purposes, and research your existing customers and
> prospects." Recruiting outreach is a named, sanctioned use. That is better
> contractual footing than most enrichment vendors offer.  RESTRICTIONS THAT
> BITE THIS PIPELINE:  1. No onward transfer of contact data — CORRECTED, THE
> PROHIBITION IS QUALIFIED. Confirmed text: "you may not transfer or disclose
> the Lookup Information to anyone else" — but the clause is conditioned on
> absence of prior written consent from RocketReach. The prior report stated the
> ban flatly and told you to restructure the engagement around it. The accurate
> position: transfer to a client is prohibited by default, and consent is
> obtainable. If the run is on behalf of a client company, either keep

**Verdict**

> RECOMMEND, but the prior report's throughput analysis was wrong and the tier
> decision changes as a result.  WHAT SURVIVED VERIFICATION. I checked every
> endpoint against the vendor's own OpenAPI-derived docs this session. Eight of
> the nine listed endpoints are confirmed exactly as to method, path, auth
> header and core fields: /person/lookup, /person/checkStatus, /bulkLookup,
> /account/, /universal/person/lookup, /universal/person/search,
> /universal/person/check_status, and /person/search's method/path/201 status.
> Nothing was invented. I added a ninth the prior report missed: GET /profile-
> company/lookup. Recruiting outreach is a named permitted use in RocketReach's
> terms ("identify candidates for recruitment purposes"), confirmed verbatim —
> stronger contractual footing than most enrichment vendors offer. Misses are
> free, B and F grade emails are free, and re-lookups are free while the plan is
> active, so retry logic costs nothing in credits.  WHAT CHANGED, AND IT
> MATTERS. The prior report's rate-limit section listed only per-minute caps and
> concluded "rate limiting is not the bottleneck; async completion latency is."
> The docs publish hourly, daily and monthly caps too, and they bind hard.
> Person Lookup on Essentials is 100/hour and 500/day — 2,000 lookups takes
> about four calendar days, not the 2.2 hours claimed. Pro is about two days.
> Only Ultimate (3,000/day) and Custom finish a 2,000-person run inside a single
> day. Two consequences: choose the tier off the DAILY cap, and build the run as
> a checkpointed, resumable job with persisted per-profile state rather than a
> single process that must survive to completion. The monthly ceiling also caps

---

## Findymail

- **Category:** enrich
- **Base URL:** https://app.findymail.com
- **Docs:** https://app.findymail.com/docs/ (OpenAPI: https://app.findymail.com/docs/openapi.yaml — re-downloaded and parsed line-by-line during this adversarial check, 2026-08-30; 160KB, 22 top-level paths + 4 sub-resource paths). Docs page footer confirms "Last updated: July 31, 2026". Marketing overview: https://www.findymail.com/api/. ADVERSARIAL CHECK RESULT: all 12 endpoints in the original report were confirmed real against the live spec — no invented and no stale paths. Corrections below are field-level, error-shape and ToS-reading fixes, plus 4 confirmed endpoints the original omitted.

**Auth**

> Authorization: Bearer {YOUR_AUTH_KEY} — plus Content-Type: application/json
> and Accept: application/json on POSTs. CONFIRMED in spec:
> securitySchemes.default = {type: http, scheme: bearer}, applied globally via a
> top-level `security: [{default: []}]` block, so every path requires it. Token
> issued at https://app.findymail.com/user/api-tokens (spec links /user/api-
> tokens). No query-param auth exists anywhere in the spec. CONFIRMED BY
> ABSENCE: grep for li_at, cookie, session_token, csrf, extension across the
> entire 160KB spec returns zero hits — there is no parameter anywhere by which
> you could supply a LinkedIn credential.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `POST` | `/api/search/business-profile` | Find work email from a LinkedIn profile URL (the primary enrichment call for this pipeline) |
| high | `POST` | `/api/search/name` | Find work email from full name plus company domain (fallback when the LinkedIn URL yields nothing, or when you only have name + employer) |
| high | `POST` | `/api/verify` | Verify an email address for deliverability |
| high | `POST` | `/api/search/employees` | Source candidate people at a company by job title — returns LinkedIn URL and job title, no email |
| high | `POST` | `/api/intellimatch/search` | Async lead search at volume (ICP query to a scored company/contact list, with optional email enrichment) |
| high | `GET` | `/api/intellimatch/status` | Poll status of an Intellimatch job |
| high | `GET` | `/api/intellimatch/data` | Fetch paginated Intellimatch results |
| high | `POST` | `/api/search/reverse-email` | Reverse lookup: email address to LinkedIn profile and optional full profile data |
| high | `POST` | `/api/search/company` | Company enrichment by LinkedIn URL, domain or name |
| high | `GET` | `/api/credits` | Check remaining credit balance (both pools) |
| high | `POST` | `/api/search/phone` | Find phone number from a LinkedIn profile URL |
| high | `POST` | `/api/search/domain` | Find contacts at a domain by role — DEPRECATED, DO NOT USE |
| high | `POST` | `/api/lookalike/search` | Find companies similar to a seed domain (ICP expansion) — CONFIRMED endpoint the original report omitted entirely |
| high | `GET` | `/api/lists` | Store enriched contacts in Findymail-side lists (CRUD) — CONFIRMED endpoints the original report omitted |
| high | `POST` | `/api/intellimatch/domains` | Manage suppression/exclusion domain lists (avoid re-contacting or targeting current employers) — CONFIRMED endpoints the original omitted |

**Rate limits**

> Global, verbatim from the spec's own `info.description`: "all endpoints have a
> concurrent rate limit of 300 simultaneous requests, unless stated otherwise."
> This is a CONCURRENCY cap, not a requests-per-minute quota — no RPM figure is
> published for the finder endpoints. Per-endpoint exceptions, all confirmed
> verbatim in the live spec: /api/search/business-profile "is limited to 30
> concurrent requests (when used synchronously)"; /api/search/domain
> (deprecated) "limited to 5 concurrent requests (when used synchronously) and
> async jobs can take up to 24 hours to be processed"; /api/technologies/search
> "Free endpoint — no credits consumed. Rate-limited to 10 requests per minute."
> CORRECTION vs original report on where 429 appears: the original said 429 is
> documented "on the Intellimatch and Technologies endpoints". Confirmed by
> line-level grep, a 429 "Too Many Attempts" is declared on FIVE paths —
> /api/intellimatch/search, /api/intellimatch/status, /api/intellimatch/data,
> /api/lookalike/search, and /api/technologies. The status and data pollers

**Pricing**

> RE-VERIFIED against https://www.findymail.com/pricing/ on 2026-08-30 — the
> original report's pricing was ACCURATE and is retained in full, with no
> staleness found. Starter: $99/month billed monthly, 5,000 Finder Credits +
> 5,000 Verifier Credits (labelled "BONUS") per month. Annual billing gives "2
> Months Free" (~17% off). Enterprise is custom pricing with custom volume,
> automatic refill, priority support and a dedicated account manager. Credit
> economics verbatim: "1 email = 1 credit OR 1 phone = 10 credits". Verifier
> credits are positioned for verifying contacts from external sources, since
> Findymail-sourced contacts arrive pre-verified. Rollover verbatim: "Unused
> credits roll over month-to-month, up to 2x your monthly allowance." Guarantees
> verbatim: "You only pay for verified results. No charge if we can't find it."
> and "Our guarantee: <5% bounce rate. If your bounce rate is higher, we refund
> your credits." SLIDER LIMITATION CONFIRMED, NOT RESOLVED: the credit-volume
> slider shows steps 1k / 5k / 15k / 30k / 50k / 100k / 100k+, but only the
> selected step renders server-side, so a fetch confirms the price for the 5k
> step only. I could not resolve the other steps from the vendor either. The
> $49/1,000 and $249/15,000 figures remain THIRD-PARTY ONLY (fullenrich.com,
> syncgtm.com, derrick-app.com) — MEDIUM confidence, not vendor-confirmed, and
> they should not be entered into a budget without a sales quote. Sizing note
> for this pipeline: at 1 credit per found email, Starter's 5,000 finder credits

**Gotchas**

- ADVERSARIAL CHECK SUMMARY (2026-08-30): every one of the original report's 12 endpoints was confirmed to exist at the exact method and path stated, against the live OpenAPI spec parsed line-by-line. No endpoint was invented, and none was stale. No endpoint was deleted from this report. The corrections below are field-level, error-shape, and one ToS misreading — plus 4 confirmed endpoints (/api/lookalike/search, the /api/lists + /api/contacts CRUD, and the /api/intellimatch exclusion-list/domain CRUD) that the original omitted and that a recruiting run will want.
- THE NOT-FOUND RESPONSE IS UNDOCUMENTED — CONFIRMED, and it remains the single biggest adapter risk. Verified by direct inspection: /api/search/name declares only 200/402/423 and /api/search/business-profile declares only 0/200/402/423. Neither declares a 404 and neither declares an empty-result body. A grep for declared 404s across the whole spec shows they exist ONLY on the exclusion-list CRUD, /api/intellimatch/data, /api/search/company, and the signals endpoints — never on the two finders you depend on. Write the adapter to treat a 200 whose payload lacks `contact`, or whose `contact.email` is missing/null/empty, as a miss. Do NOT assume a 404 and do NOT let a KeyError on response['contact']['email'] crash the run. Make a deliberate junk lookup your first integration test and pin the parser to the observed shape.
- CORRECTED: the original said the spec declares response code 0 (async) for BOTH /api/search/name and /api/search/business-profile. It does not. Only /api/search/business-profile (and the deprecated /api/search/domain) declare a separate code 0. /api/search/name declares 200/402/423, with the async acknowledgement modelled as a `oneOf` branch INSIDE the 200. Consequence for the adapter: the two finders behave differently in webhook mode, so you cannot branch on HTTP status alone to tell sync from async — inspect the body for `contact` vs `payload` on both endpoints instead.
- CORRECTED / NEW: ERROR BODIES USE TWO DIFFERENT KEY NAMES. The finder and verifier endpoints return {"error": "..."} for 402 and 423. The Intellimatch, lookalike and technologies endpoints return {"message": "..."} for 401, 422, 423 and 429 — including a DIFFERENT paused-subscription string ("Your subscription is currently paused." vs the finders' "Subscription is paused"). An error handler that reads only `error` will log empty strings for every Intellimatch failure. Read both keys.
- CORRECTED / NEW: Intellimatch `config.target_job_titles` is ORDERED PRIORITY TIERS with a HARD MAX OF 3 TIERS — verbatim, "3 tiers max: a request with more is rejected". Tier 1 is tried first and it falls back to the next tier only on no match. A flat list is accepted and treated as one tier. Default is [["CEO"]]. The original showed the nested-array syntax without stating the cap, so a 4-tier seniority ladder — an obvious thing to write for a recruiting funnel — gets rejected at 422.
- CORRECTED / NEW: Intellimatch `config.exclusion_filter_list_ids` DEFAULTS TO [0], which verbatim means "global exclusion list" — passing nothing silently filters your results against your account's global exclusion list. Pass [-1] for no filter. The original documented the field without its default, so a run can come back mysteriously short.
- NEW (cost control the original missed): Intellimatch `config.require_email: true` states verbatim that "Companies without email are excluded and not charged." Combined with find_contact + find_email, this makes Intellimatch the only path where you can request volume and pay strictly for delivered emails. Turn it on.
- CORRECTED: /api/search/employees requires BOTH `website` and `job_titles` (the original's notes described only `count`'s limits). `job_titles` is capped at max 10. Also: its 200 is a BARE JSON ARRAY, not an object — a response parser written for the finders' {"contact": ...} envelope will break on it.
- PATH TRAP CONFIRMED AND RESOLVED: the credit-reporting endpoints are GET /api/credits/report/summary and GET /api/credits/report/team-summary (slash- separated), as declared in the OpenAPI spec. The rendered HTML docs page displays them as anchor slugs 'api/credits-report-summary' and 'api/credits- report-team-summary' (hyphenated). The hyphenated forms are a docs-rendering artifact and are NOT callable. The original report had these right; this note exists because reading the HTML docs page instead of the spec will lead you to the wrong path.
- DOCUMENTED CONTRADICTION ON VERIFIER CHARGING — resolve with the vendor before budgeting. The OpenAPI spec and docs say /api/verify "Uses one verifier credit on all attempted verification" (you pay on every attempt). The marketing page at findymail.com/api/ says the Email Verifier charges "1 credit per successful response". These cannot both be true. Budget on the pessimistic spec wording (charged always), but this is worth one email to sales, since at scale the difference is material.
- Charging rules are NOT uniform, so a single 'credits used' counter will be wrong. Finders (/api/search/name, /api/search/business-profile, /api/search/company) charge 1 credit ONLY on a found result. /api/verify charges 1 verifier credit on EVERY attempt (see contradiction above). /api/search/employees charges 1 per found contact and returns no email. /api/search/phone charges 10. /api/search/reverse-email charges 1, or 2 with with_profile. /api/lookalike/search charges 1 per 10 results, rounded up. Only /api/lookalike/search returns `credits_used` in its own response body.
- Two credit pools, not one. GET /api/credits returns {credits, verifier_credits} as separate integers. Finder and verifier credits are not interchangeable; you can be flush in one and empty in the other.
- Do not double-pay for verification. Findymail states its finder results are already verified and that verifier credits exist for contacts from external sources. Piping every /api/search/* result through /api/verify burns a verifier credit to re-confirm something already confirmed. Only verify addresses that came from elsewhere.
- /api/verify's 200 is declared content-type text/plain with schema type:string, and its example — { "email": "john@example.com", "verified" : true, "provider": 'Google'} — uses a SINGLE-QUOTED provider value, so it is not valid JSON as printed. CONFIRMED verbatim in the live spec. Do not assume a clean JSON body; parse defensively and log the raw response the first time you call it.

**Terms and account risk**

> Re-read https://www.findymail.com/terms-conditions/ on 2026-08-30. Most of the
> original report's reading is CONFIRMED; one clause was misread and is
> corrected below. CONFIRMED: (1) The terms incorporate a separate Acceptable
> Use Policy by reference — verbatim "You will comply with our Acceptable Use
> Policy ("AUP")" — and I independently attempted to locate the AUP document via
> search and failed. The original report's caveat holds: the specific
> prohibited-use list is UNVERIFIED and unread. This remains the single unread
> document material to the decision. (2) Nothing in the terms restricts the
> customer from sending cold email; GDPR/CAN-SPAM compliance is pushed to the
> customer via an incorporated DPA — verbatim "The terms of the DPA are hereby
> incorporated by reference and will apply to the extent any Customer Data
> includes Personal Data." Recruiting outreach to EU-resident candidates is your
> legitimate-interest assessment to make. (3) Monitoring and suspension
> confirmed — verbatim "We reserve the right to monitor your use of the

**Verdict**

> RECOMMEND for this pipeline — and the recommendation survives adversarial
> checking. The central risk this review was run to catch, invented or stale
> endpoints, did not materialize: all 12 endpoints in the original report were
> confirmed at the exact method and path against the live OpenAPI spec (parsed
> directly, not summarized), the docs page confirms "Last updated: July 31,
> 2026", and nothing was deleted. Both enrichment paths you need are first-class
> documented endpoints: POST /api/search/business-profile takes a LinkedIn URL,
> POST /api/search/name takes name + domain, and both return the same flat
> {"contact": {name, domain, email}} shape, so one parser covers both and the
> fallback chain is trivial. Auth is a plain bearer token, applied globally.
> Verification lives in the same account at POST /api/verify. Answering your
> original question: YES, the finders charge only for verified emails — the spec
> says "Uses one finder credit if a verified email is found" on both, and the
> pricing page says "You only pay for verified results. No charge if we can't
> find it." The verifier is the exception and charges on every attempt, so do
> not reflexively re-verify Findymail's own output. Volume is a non-issue:
> 300-2000 contacts per role sits far inside the 30-concurrent LinkedIn cap, and
> Starter's 5,000 monthly credits covers roughly two to three full roles. On
> account safety, which you named as binding alongside correctness, the
> verification strengthened the case rather than weakening it: a grep of the
> entire spec for li_at, cookie, session_token and csrf returns zero hits, so
> there is no parameter through which a LinkedIn credential could be supplied

---

## Dropcontact + Prospeo + Datagma (three vendors in one report)

- **Category:** enrich
- **Base URL:** Dropcontact: https://api.dropcontact.com/v1 (confirmed) | Prospeo: https://api.prospeo.io (confirmed on the authentication page) | Datagma: https://gateway.datagma.net (confirmed; docs also show a plain-http variant — always use https)
- **Docs:** Dropcontact: https://developer.dropcontact.com (verified 2026-08-30) | Prospeo: https://prospeo.io/api-docs (auth: https://prospeo.io/api-docs/authentication, limits: https://prospeo.io/api-docs/rate-limits, person schema: https://prospeo.io/api-docs/person-object — all verified 2026-08-30) | Datagma: https://datagmaapi.readme.io/reference (index: https://datagmaapi.readme.io/llms.txt; any page also served as markdown by appending .md — verified 2026-08-30). Datagma billing/policy answers live on a SEPARATE host: https://help.datagma.com

**Auth**

> Dropcontact: `X-Access-Token: <api_key>` header (confirmed on
> developer.dropcontact.com). Prospeo: `X-KEY: <api_key>` header AND `Content-
> Type: application/json` mandatory; HTTPS required; all endpoints POST except
> Account Information (GET) — confirmed on prospeo.io/api-docs/authentication.
> Datagma: NO header — the key is the `apiId` QUERY-STRING parameter, e.g.
> `?apiId=<api_key>`; key from https://app.datagma.com/user-api (confirmed on
> both Datagma reference pages).

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `POST` | `/enrich-person` | PROSPEO — single LinkedIn-URL-to-email enrichment. Best-fit primary of the three: one synchronous POST, native person-LinkedIn-URL input, verified-onl |
| high | `POST` | `/bulk-enrich-person` | PROSPEO — batch enrichment, up to 50 people per call, SYNCHRONOUS (no job id, no polling). |
| high | `POST` | `/enrich/all` | DROPCONTACT — submit a batch enrichment job (step 1 of 2). Async: returns a request_id you must poll. |
| high | `GET` | `/enrich/all/{request_id}` | DROPCONTACT — fetch results of a submitted batch (step 2 of 2). Poll until success is true. |
| high | `GET` | `/api/ingress/v2/full` | DATAGMA — enrich a PERSON from their LinkedIn profile URL and return a work email. This is the correct Datagma path for LinkedIn-URL-to-email; findEma |
| high | `GET` | `/api/ingress/v8/findEmail` | DATAGMA — find a work email from name + company. Use only as the name-based fallback leg; it does NOT take a person LinkedIn URL. |

**Rate limits**

> DROPCONTACT (vendor docs, re-confirmed 2026-08-30) — 60 requests per second.
> Batch cap 250 contacts per POST /enrich/all, 15 kB per contact. Third-
> party/community guidance (n8n template, medium confidence, NOT re-verified
> this session) describes practical throughput near 250 contacts per 10 minutes
> (~1,500/hour) — that is processing pace, not the HTTP limit. Assume a
> 2,000-row batch resolves over about an hour, not seconds. PROSPEO (vendor docs
> at /api-docs/rate-limits, re-confirmed 2026-08-30, now with the per-second
> search figures the original report omitted) — Enrich endpoints (/enrich-
> person, /enrich-company, /bulk-enrich-person, /bulk-enrich-company): Starter
> 5/sec, 300/min, 2,000/day; Growth 5/sec, 300/min, 5,000/day; Pro 30/sec,
> 1,800/min, 500,000/day. Search endpoints (/search-person, /search-company):
> Starter 1/sec, 30/min, 1,000/day; Growth 2/sec, 60/min, 4,000/day; Pro 5/sec,
> 180/min, 250,000/day. Exceeding returns HTTP 429. NEW confirmed detail:
> responses carry `x-daily-request-left` and `x-minute-request-left` headers —

**Pricing**

> DROPCONTACT (re-read 2026-08-30 at https://www.dropcontact.com/pricing —
> figures in the original report CONFIRMED unchanged) — Starter EUR 79/mo (EUR
> 63.20/mo annual), 500 credits/mo, includes pay-on-success, B2B email
> enrichment, email validation, catch-all verification, GDPR compliance, file
> enrichment, API & MCP access, Google Sheets add-on. Growth EUR 120/mo (EUR
> 96/mo annual), 500 credits/mo base, adds credit carry-over, "LinkedIn
> enrichment without login requirements", LinkedIn URL enrichment, job cleaning,
> AI job classification, company-change detection, domain matching, company data
> enrichment. Enterprise custom, from 200,000 credits/month, adds priority
> enrichment, real-time notifications, dedicated support. 20% annual discount.
> Pay-on-success: credits are returned when no email is found. API access IS on
> Starter; LinkedIn enrichment is NOT. PROSPEO (still NOT vendor-confirmed — see
> gotchas) — the vendor's own /pricing page again returned only a page title on
> fetch this session. The same figures are now corroborated by FOUR independent
> third parties (ColdIQ 2026-06-02, FullEnrich, Derrick, SyncGTM, all
> 2026-dated) which agree exactly: Free $0 (75 credits/mo + 100 Chrome-extension
> credits), Starter $39/mo (1,000 credits), Growth $99/mo (5,000), Pro $199/mo
> (20,000), Business $369/mo (50,000). Plan names Starter/Growth/Pro match the
> vendor's own rate-limits doc, which I did read. Annual billing reportedly does
> NOT reduce the per-month rate. API access on all tiers including Free. Credit

**Gotchas**

- VERIFICATION PASS, 2026-08-30 — ALL SIX ENDPOINTS CONFIRMED. Every method, path, base URL, auth scheme and headline limit in the original report was checked against the vendors' own live documentation. Nothing was invented and nothing was deleted. Prospeo POST /enrich-person and POST /bulk-enrich- person confirmed on prospeo.io/api-docs; Dropcontact POST /enrich/all, GET /enrich/all/{request_id} and the three /enrich/webhook methods confirmed on developer.dropcontact.com; Datagma GET /api/ingress/v2/full and GET /api/ingress/v8/findEmail confirmed on datagmaapi.readme.io. The corrections below are field-level, one overstated claim, and one mis-sourced claim.
- CORRECTED — DROPCONTACT's LinkedIn limitation was OVERSTATED in the original report. The original said flatly that 'a LinkedIn profile URL ALONE will not resolve an email'. The vendor's own support article (support.dropcontact.com/article/207, now redirecting to www.dropcontact.com/article/207) actually says BOTH things: you can 'enrich your contacts using only their LinkedIn profile URL', AND 'No company: Without a company name, Dropcontact can't find an email.' The reconciliation is that Dropcontact derives the company FROM the profile, so a bare person URL is a documented input, not a guaranteed miss. Practical guidance is unchanged — put a vendor with a native bare-URL contract ahead of Dropcontact — but do not tell an engineer the call is futile, because it is documented to work and you will be contradicted by the docs. The hard requirement is name + a company identifier (company na
- NEW — DROPCONTACT: Sales Navigator URLs are NOT supported. The same support article states only public readable LinkedIn URLs work; private redirected Sales Navigator links are rejected. If your sourcing step emits Sales Navigator URLs, normalise them to public /in/ URLs before the Dropcontact leg or you will book misses as coverage gaps.
- NEW — DROPCONTACT: the `email` field in the GET results is an ARRAY of objects each carrying a qualification, not a bare string. Code written against `record.email` as a string will break on the first result. Also confirmed: a 15 kB per-contact size cap on POST /enrich/all, which a large custom_fields payload can breach.
- NEW — DROPCONTACT: GET /enrich/all/{request_id} accepts an optional `forceResults=true` query parameter to return partial results before the job finishes. Useful for a progress UI; do not use it as the completion check — still gate on success:true.
- CORRECTED — PROSPEO bulk response keys. The original report described 'matched records, unmatched identifiers, and invalid datapoints' in prose. The exact documented keys are {error, total_cost, matched:[{identifier, person, company}], not_matched:[identifiers], invalid_datapoints:[identifiers]}. `total_cost` is a free per-call credit meter — log it. Join on `identifier`; the response is not index-aligned with your request array.
- NEW — PROSPEO error model, and it is the likeliest source of a broken adapter. Every documented failure except rate-limiting returns HTTP 400 with a code string: NO_MATCH, INVALID_DATAPOINTS, INSUFFICIENT_CREDITS, INVALID_API_KEY, INVALID_REQUEST, INTERNAL_ERROR. A bad API key is a 400, not a 401. A server fault is a 400, not a 500. Retry logic keyed on HTTP status will retry unauthenticated calls forever and never retry a genuine transient. Branch on the code field. Only 429 has its own status.
- NEW — PROSPEO: responses carry `x-daily-request-left` and `x-minute-request- left` headers. Drive your throttle off those instead of hard-coding the plan table.
- CONFIRMED — PROSPEO plan-tier DAILY enrich caps bite before per-second limits do: Starter 2,000/day, Growth 5,000/day, Pro 500,000/day. One 2,000-person role exhausts Starter in a single run. Growth is the realistic floor for the stated volume. Per-second is 5 on both Starter and Growth, so paying up buys daily headroom, not burst speed.
- CONFIRMED — PROSPEO: pass only_verified_email:true. Default returns unverified addresses, the wrong trade for a cold sequence off a dedicated domain. only_verified_mobile also exists if you ever turn mobile on.
- CONFIRMED — PROSPEO: re-enriching the same record within 90 days is free, so idempotent retries are cheap — but a cached stale result can come back. If a role reruns months apart, do not assume the second run resolves from scratch.
- CORRECTED SOURCE — DATAGMA 'Most Probable Email Output' is REAL but is NOT documented in the API reference. It is not on the scoring page or the fields page; it lives in the help centre at help.datagma.com/en/articles/8820217. Vendor wording: it is the term used for catch-all addresses Datagma cannot verify, and 'You are not billed for any queries that result in a Most Probable Email Output.' The substance of the original gotcha stands: unbilled is not free — sending to those addresses damages a dedicated cold- email domain. Gate strictly on the status field. The correction matters because an engineer told to find this in the API reference will not find it and may conclude the whole gotcha was invented.
- CONFIRMED — DATAGMA: /findEmail's `linkedInSlug` is a COMPANY LinkedIn URL, quoted verbatim from the reference as 'Linkedin Company Slug URL. If you do not have the domain, we will extract it for you.' Passing a /in/ person URL there is a silent mismatch, not an error. Person-LinkedIn-URL-to-email goes through GET /api/ingress/v2/full with the `data` parameter. This remains the single most likely wrong-but-silent adapter here.
- CONFIRMED — DATAGMA version split is real and both pages are live. The reference page 'Find Work Verified Email' documents /api/ingress/v8/findEmail; the guide page 'Find a work email address' still documents /api/ingress/v6/findEmail, with a working example URL and two extra params, findEmailV2Step (3 = email, 2 = domain only, identical cost) and findEmailV2Country ('General' if unknown). Build against v8; keep v6 as the documented fallback if v8 404s.

**Terms and account risk**

> I did not read the full Terms of Service of any of the three this session. The
> following comes from docs, pricing and help-centre pages only, and should be
> confirmed by counsel before a production recruiting run. LINKEDIN ACCOUNT
> SAFETY: none of the three asks for your LinkedIn session cookie or credentials
> in any documented request — every one takes a URL or a name and resolves it
> server-side. Dropcontact's own pricing page now states this explicitly,
> listing "LinkedIn enrichment without login requirements" as a Growth feature
> (confirmed 2026-08-30), which is direct vendor corroboration. So the
> enrichment leg carries no ban risk for your own LinkedIn account, unlike
> cookie-driven scrapers. CORRECTION: the original report's claim that Prospeo's
> LinkedIn Email Finder extracts profile data "in real-time" was NOT re-verified
> this session — drop it from the reasoning; the header-and-URL-only request
> contract is the part that is actually confirmed. The SOURCING leg (finding
> profiles matching an ICP) is where LinkedIn ToS exposure actually lives, and

**Verdict**

> VERIFIED 2026-08-30. All six endpoints survive the adversarial pass — nothing
> invented, nothing stale, nothing deleted. The original report was accurate on
> paths, methods, auth and limits. Three things needed fixing: one overstated
> claim, one mis-sourced claim, and a set of field-level details that would have
> produced a broken adapter. The recommendation is unchanged.  RECOMMEND all
> three, as a three-leg waterfall in a forced order — and Dropcontact still
> cannot be first.  PROSPEO — RECOMMEND as primary, confidence raised. Every
> path, header, field, credit cost, error code and rate limit was read on
> prospeo.io's own docs this session. It is the only one of the three that is a
> clean fit for the exact operation: bare LinkedIn profile URL in, verified work
> email out, one synchronous POST, no polling, no job state. only_verified_email
> maps directly onto the domain-reputation priority; the 50-record synchronous
> bulk endpoint keeps a 2,000-person role to 40 calls. Take Growth ($99) not
> Starter — the 2,000/day enrich cap on Starter is exhausted by a single large
> role, and per-second is identical (5/sec) on both, so you are buying daily
> headroom. TWO THINGS THE ORIGINAL REPORT GOT WRONG AND YOU MUST BUILD AROUND:
> the bulk response keys are {error, total_cost, matched, not_matched,
> invalid_datapoints}, and every error including a bad API key returns HTTP 400
> with a code string, not a meaningful status. Retry logic keyed on HTTP status
> will misbehave. The one open item is pricing: the vendor's /pricing page will
> not render, so the dollar figures remain third-party-sourced, though four
> independent 2026 sources now agree exactly. Confirm in the dashboard before

---

## MillionVerifier + NeverBounce + ZeroBounce (three vendors in one report; each endpoint's `purpose` is prefixed with the vendor name). ADVERSARIALLY RE-VERIFIED 2026-08-30 against live vendor documentation.

- **Category:** verify
- **Base URL:** MillionVerifier single: https://api.millionverifier.com | MillionVerifier bulk: https://bulkapi.millionverifier.com | NeverBounce: https://api.neverbounce.com/v4.2 | ZeroBounce single+batch+account: https://api.zerobounce.net (regional: https://api-us.zerobounce.net, https://api-eu.zerobounce.net — same paths, data-residency only) | ZeroBounce file/bulk: https://bulkapi.zerobounce.net
- **Docs:** https://developer.millionverifier.com/ (Redoc page with the full OpenAPI spec embedded in the HTML — grep the page source for verbatim enums) | https://developers.neverbounce.com/reference/single-check (append .md to ANY page URL for clean markdown + embedded OpenAPI; index at https://developers.neverbounce.com/llms.txt) | https://www.zerobounce.net/docs/email-validation-api-quickstart/ (status/sub_status authority: .../v2-status-codes/ ; rate limits: https://www.zerobounce.net/docs/api-dashboard/api-rate-limits/)

**Auth**

> All three are query-string API keys. No bearer tokens, no auth headers.
> MillionVerifier single API (including /api/v3/credits): `?api=<key>` — spec
> parameter name "api", in: query. MillionVerifier bulk API: `?key=<key>` —
> different param name, confirmed on every /bulkapi/* operation. NeverBounce:
> `?key=<key>` (securityScheme apiKey / in: query / name: key); for POST
> endpoints the key goes in the JSON body as `"key"`. ZeroBounce:
> `?api_key=<key>`; for POST /v2/validatebatch in the JSON body as `"api_key"`;
> for POST /v2/sendfile as a multipart form field `api_key`.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `GET` | `https://api.millionverifier.com/api/v3` | [MillionVerifier] Single-email real-time verification. THE endpoint for a per-address adapter. |
| high | `GET` | `https://api.millionverifier.com/api/v3/credits` | [MillionVerifier] Remaining credit balance |
| high | `POST` | `https://bulkapi.millionverifier.com/bulkapi/v2/upload` | [MillionVerifier] Bulk file upload (CSV/TXT list) |
| high | `GET` | `https://bulkapi.millionverifier.com/bulkapi/v2/fileinfo` | [MillionVerifier] Bulk file status / progress |
| high | `GET` | `https://bulkapi.millionverifier.com/bulkapi/v2/filelist` | [MillionVerifier] List uploaded bulk files (filterable) |
| high | `GET` | `https://bulkapi.millionverifier.com/bulkapi/v2/download` | [MillionVerifier] Download bulk results CSV |
| high | `GET` | `https://bulkapi.millionverifier.com/bulkapi/stop` | [MillionVerifier] Stop an in-progress bulk file |
| high | `GET` | `https://bulkapi.millionverifier.com/bulkapi/v2/delete` | [MillionVerifier] Delete a bulk file |
| high | `GET` | `https://api.neverbounce.com/v4.2/single/check` | [NeverBounce] Single-email verification. NOTE: vendor policy forbids using this for list verification — see tosRisk. |
| high | `POST` | `https://api.neverbounce.com/v4.2/jobs/create` | [NeverBounce] Create a bulk verification job (the sanctioned path for list verification) |
| high | `POST` | `https://api.neverbounce.com/v4.2/jobs/parse` | [NeverBounce] Parse a created job (only needed if auto_parse was false) |
| high | `POST` | `https://api.neverbounce.com/v4.2/jobs/start` | [NeverBounce] Start a parsed job (only needed if auto_start was false) |
| high | `GET` | `https://api.neverbounce.com/v4.2/jobs/status` | [NeverBounce] Poll job status |
| high | `GET` | `https://api.neverbounce.com/v4.2/jobs/results` | [NeverBounce] Paged JSON results for a job |
| high | `GET` | `https://api.neverbounce.com/v4.2/jobs/download` | [NeverBounce] Download job results as CSV |
| high | `GET` | `https://api.neverbounce.com/v4.2/jobs/search` | [NeverBounce] Search/list jobs |
| high | `POST` | `https://api.neverbounce.com/v4.2/jobs/delete` | [NeverBounce] Delete a job |
| high | `GET` | `https://api.neverbounce.com/v4.2/account/info` | [NeverBounce] Account info / credit balance |
| high | `GET` | `https://api.zerobounce.net/v2/validate` | [ZeroBounce] Single-email validation. THE endpoint for a per-address adapter. |
| high | `POST` | `https://api.zerobounce.net/v2/validatebatch` | [ZeroBounce] Real-time batch validation (synchronous) — HARD CAP 100 EMAILS PER CALL |
| high | `POST` | `https://bulkapi.zerobounce.net/v2/sendfile` | [ZeroBounce] Submit a CSV/TXT file for async bulk validation |
| high | `GET` | `https://bulkapi.zerobounce.net/v2/filestatus` | [ZeroBounce] Poll bulk file processing status |
| high | `GET` | `https://bulkapi.zerobounce.net/v2/getfile` | [ZeroBounce] Download bulk validation results |
| high | `GET` | `https://bulkapi.zerobounce.net/v2/deletefile` | [ZeroBounce] Delete a bulk file |
| high | `GET` | `https://api.zerobounce.net/v2/getcredits` | [ZeroBounce] Credit balance |
| high | `GET` | `https://api.zerobounce.net/v2/getapiusage` | [ZeroBounce] API usage stats |

**Rate limits**

> MillionVerifier: 160 requests/second on the single API — re-confirmed verbatim
> 2026-08-30 at help.millionverifier.com/email-verification-api/real-time-api
> ("The rate limit for single API calls is 160 requests per second"). No
> documented daily cap. Single-endpoint `timeout` param 2-60s, default 20. Note
> the developer.millionverifier.com API reference itself documents no rate
> limit; the number lives only in the help center.  NeverBounce: no published
> requests-per-second number, but hard structural limits on the bulk API, all
> re-confirmed verbatim 2026-08-30 at
> developers.neverbounce.com/reference/usage-guidelines.md — "We allow each
> account to run 10 concurrent jobs", "maximum of 50 runs per day", "Do NOT
> create more than 10 jobs for every 100k items per hour", and "there is a
> maximum payload of 25MB enforced. If you surpass this limit you'll receive a
> 413 error code." Rate-limit rejections surface as a 200 response with
> status=throttle_triggered, not an HTTP 429 (confirmed: throttle_triggered

**Pricing**

> All three sell one-time credit packs (not subscriptions) at the volumes this
> pipeline needs.  MillionVerifier — RE-VERIFIED 2026-08-30, EXACT MATCH to the
> prior report, no drift. Pulled the `allPackages` array verbatim from
> https://www.millionverifier.com/assets/js/main.js: 10,000/$39 ($3.90 per 1k);
> 25,000/$59 ($2.36); 50,000/$89 ($1.78); 100,000/$149 ($1.49); 500,000/$299
> ($0.60); 1,000,000/$449 ($0.449); 2,000,000/$799; 3,000,000/$1,099;
> 4,000,000/$1,399; 5,000,000/$1,599; 10,000,000/$2,599; 25,000,000/$4,999;
> 50,000,000/$8,499 ($0.17). Smallest purchasable pack is 10K. Confidence: HIGH.
> CAVEAT ADDED: the secondary claims attached to MillionVerifier pricing in the
> prior report — credits never expire, no charge for catch-all results, refund
> if hard-bounce rate exceeds 4% — were NOT re-verified this session (the help-
> center pages behind them were not opened). Treat those three as unconfirmed
> marketing claims, not contract terms.  ZeroBounce — RE-VERIFIED 2026-08-30
> from the schema.org Offer objects embedded in
> https://www.zerobounce.net/pricing/ (priceValidUntil 2026-12-31 confirmed).
> Every figure in the prior report is correct, and TWO TIERS WERE MISSING:
> 2,000/$39 ($19.50 per 1k); 5,000/$69 ($13.80); 10,000/$129 ($12.90);
> 25,000/$274 ($10.96); 50,000/$499 ($9.98); 100,000/$649 ($6.49);
> 250,000/$1,299 ($5.20); 500,000/$2,199 ($4.40); 1M/$3,199 ($3.20); **2M/$5,999
> ($3.00)**; **5M/$13,499 ($2.70)**; 10M/$26,998 ($2.70). $39/2,000 is the

**Gotchas**

- CHANGE LOG — what this adversarial pass corrected. (1) ZeroBounce /v2/validatebatch max batch size was WRONG: the prior report said 'a few hundred per call' and 'no explicit max'; the vendor rate-limits page states 100 emails per request and 30 requests/minute. (2) NeverBounce single/check `retry_token` was INVENTED and has been deleted — 0 occurrences in the vendor page or its OpenAPI. (3) ZeroBounce getcredits UPGRADED medium->high, path confirmed correct. (4) ZeroBounce getapiusage UPGRADED low->high, path confirmed correct. (5) MillionVerifier subresult enum corrected 32->33 values, full list now included. (6) MillionVerifier demo-key list was missing API_KEY_FOR_DISPOSABLE and API_KEY_FOR_ERROR_NO_EMAIL. (7) NeverBounce jobs/status verdict field pinned as `job_status` (not `status`) with the full 9-value enum. (8) ZeroBounce getfile `download_type` param added. (9) ZeroBounce price 
- MillionVerifier's /bulkapi/stop path anomaly is REAL, not a transcription error — and it is a trap for automated verification. Grepping the raw developer.millionverifier.com page source gives 9 hits for `bulkapi.millionverifier.com/bulkapi/stop` and 0 hits for `/bulkapi/v2/stop`, while all five sibling operations carry `/v2/`. An LLM- summarized read of that same page silently 'normalizes' it to /bulkapi/v2/stop. If you verify vendor paths by asking a model to summarize a doc page, you will get the wrong path here. Read the source, and probe both spellings once against a live key.
- The three verdict vocabularies collide on catch-all and DO NOT map 1:1. MillionVerifier `catch_all` (underscore), NeverBounce `catchall` (one word), ZeroBounce `catch-all` (hyphen). Normalize to your own internal enum at the adapter boundary and never string-compare across vendors.
- MillionVerifier uses a DIFFERENT auth query param per host: `api` on api.millionverifier.com (single API AND /api/v3/credits) and `key` on bulkapi.millionverifier.com (all bulk ops). Same key value, different param name. Still the single most likely copy-paste bug in the adapter.
- MillionVerifier returns HTTP 200 with result="error" and a populated `error` string for bad keys and missing emails. Status-code-only error handling will silently record an unverified address as an error-shaped success. Branch on the body.
- ZeroBounce getcredits has the same class of failure: an invalid API key returns a well-formed body {"Credits":-1} rather than an auth error. Any 'do we have credits left?' preflight must test for -1 explicitly, or a bad key reads as a zero-ish balance instead of an auth failure — and then your retry loop starts burning toward the 200-bad-key/hour block.
- ZeroBounce blocks your key for a full hour after 200 bad-API-key requests within an hour. A misconfigured key inside an automatic retry loop will burn through that in seconds. Fail fast on the first auth error; never retry it.
- ZeroBounce /v2/validatebatch is capped at 100 emails per request and 30 requests per minute (40 on ZeroBounce ONE). A 2,000-address role is 20 calls, which is fine — but code that assumed 'a few hundred per call' will either get rejected or silently truncate. Size the chunker at 100 and rate- limit to 30/min.
- If you set allow_phase_2=true on ZeroBounce /v2/sendfile to resolve catch- alls, you MUST pass download_type=combined (or phase_2) on /v2/getfile. The default returns phase-1 results only, so Verify+ appears to have done nothing and every catch-all still reads as catch-all. This param was missing from the prior report and is easy to miss because it is on a different endpoint from the flag that enables the feature.
- NeverBounce wraps every 2xx response in a request-level `status` field separate from the per-email `result` field. Confirmed enum: success, general_failure, auth_failure, temp_unavail, throttle_triggered, bad_referrer. Errors including rate limiting arrive as HTTP 200 with status != success and a `message` string — check `status` before reading `result`, and treat throttle_triggered as retry-with-backoff, not a verdict.
- NeverBounce /jobs/status returns BOTH a request-level `status` and a job- level `job_status` on the same object. Reading `status` when you meant `job_status` gives you the string 'success' forever and your poll loop never terminates. Full job_status enum: under_review, queued, failed, complete, running, parsing, waiting, waiting_analyzed, uploading. The vendor's OpenAPI types job_status as a plain string with no enum, so parse defensively.
- NeverBounce jobs can enter `under_review` (human QA queue) and sit up to one business day. Pass allow_manual_review=false at /jobs/create for an unattended pipeline, or the per-role run stalls overnight with no error. account/info exposes job_counts.under_review as a cheap way to detect this across all jobs at once.
- NeverBounce /jobs/start is irreversible: credits deduct and the job cannot be stopped or restarted. Use run_sample first for a bounce-rate estimate before paying.
- NeverBounce single/check over x-www-form-urlencoded must encode '+' in plus- aliases as %2B, quoted verbatim by the vendor: the '+' character 'is treated as a non-breaking space when the string is decoded'. Relevant because recruiting enrichment does surface plus-aliases.

**Terms and account risk**

> THE DECIDING ISSUE FOR THIS PIPELINE, AND IT SURVIVED RE-VERIFICATION
> UNCHANGED — NeverBounce explicitly prohibits the exact usage pattern a per-
> address adapter implements. Re-read verbatim 2026-08-30 from
> https://developers.neverbounce.com/reference/usage-guidelines.md: "Do NOT use
> single verification for verifying emails in an existing list or database one-
> by-one" and "Your account may be locked and API access disabled if used for
> this purpose." An enrich-then-verify-each-address loop over a 300-2,000 person
> ICP list is a list being verified one-by-one. The same page repeats the
> account-lock threat for small-job spam — "Do NOT create more than 10 jobs for
> every 100k items per hour. Sending too many small jobs in a short amount of
> time can result in your account being locked and API access disabled" —
> alongside the 10-concurrent-job and 50-runs-per-day caps. Since account safety
> is a stated hard constraint, NeverBounce's single/check is off the table for
> this design; complying means batching each role's list into one /jobs/create

**Verdict**

> RECOMMEND ZeroBounce as primary; MillionVerifier acceptable as a cost-
> efficient second source; AVOID NeverBounce for this pipeline's shape. The re-
> verification did not change the ranking — the evidence underpinning it held up
> — but it changed the ZeroBounce implementation plan materially.  ZeroBounce
> (recommend). It remains the only one of the three whose verdict taxonomy
> separates spamtrap, abuse, and toxic/possible_trap from ordinary invalidity,
> now re-confirmed verbatim against /v2-status-codes/. That distinction is the
> whole ballgame for a dedicated cold-email domain sending 15-40/day: one
> spamtrap hit does far more damage than a hundred soft bounces, and neither of
> the other two will tell you it happened. Its per-address real-time API is
> explicitly sold for programmatic use (80k requests/10s), credits never expire,
> and it offers the only vendor-side catch-all resolution mechanism (Verify+ /
> allow_phase_2) — which matters because a recruiting ICP of corporate mailboxes
> is catch-all-heavy. It is the most expensive of the three at this volume
> ($13.80/1k at the 5K tier, about $28 for a 2,000-person role), which is
> irrelevant given budget is explicitly not the constraint. IMPLEMENTATION
> CHANGE FROM THE PRIOR REPORT: wire GET /v2/validate per address as before, but
> if you use /v2/validatebatch for backfills, chunk at 100 addresses per call
> and throttle to 30 calls/minute — the prior report's 'a few hundred per call'
> figure was wrong and would have produced rejected or truncated batches. And if
> you enable allow_phase_2 on bulk files, pass download_type=combined on getfile
> or the catch-all resolution you paid for never reaches your data.

---

## Instantly.ai

- **Category:** send
- **Base URL:** https://api.instantly.ai/api/v2 (verified: the OpenAPI `servers` entry is exactly [{"url":"https://api.instantly.ai"}] and all 184 paths carry the /api/v2 prefix)
- **Docs:** https://developer.instantly.ai/ — machine-readable spec (authoritative; downloaded and parsed this session, 4.2 MB): https://api.instantly.ai/openapi/api_v2.json (OpenAPI 3.1.0, info.version 2.0.0, 184 paths). Page index: https://developer.instantly.ai/llms.txt (every page fetchable as .md). Migration: https://developer.instantly.ai/guides/api-v1-migration ; rate limits: https://developer.instantly.ai/getting-started/rate-limit ; webhook payloads: https://developer.instantly.ai/guides/webhook-events

**Auth**

> Authorization: Bearer <API_V2_KEY>. Verified two ways:
> components.securitySchemes.ApiKeyAuth = {type: http, scheme: bearer} applied
> as a global `security` requirement across the spec, and the Authorization docs
> page says "Add a new `header` to your request, called `authorization`, with
> the value: `Bearer {{key}}`". Keys are workspace-scoped, created in the app
> (Settings > Integrations > API Keys) or via POST /api/v2/api-keys. Scopes are
> `<resource>:<action>` strings from a closed enum of 178 values (action in
> all|create|read|update|delete). A v1 key will NOT authenticate against v2 —
> the help center states "API v2 is not compatible with API v1. A new API key
> must be generated for v2 endpoints." NOTE: the key is displayed only once at
> creation and cannot be recovered.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `POST` | `/api/v2/campaigns` | Create a campaign (the 3-step sequence, schedule, sending accounts, daily limit) |
| high | `GET` | `/api/v2/campaigns` | List campaigns (paginated) |
| high | `GET` | `/api/v2/campaigns/{id}` | Get a single campaign (read status, email_list, sequences) |
| high | `PATCH` | `/api/v2/campaigns/{id}` | Update a campaign (change daily_limit, sending accounts, sequence copy, schedule) |
| high | `POST` | `/api/v2/campaigns/{id}/activate` | Activate (start) or resume a campaign |
| high | `POST` | `/api/v2/campaigns/{id}/pause` | Stop (pause) a campaign |
| high | `POST` | `/api/v2/leads/add` | Add leads in bulk to a campaign (the main ingestion call) - includes custom variables |
| high | `POST` | `/api/v2/leads` | Create a single lead |
| high | `POST` | `/api/v2/leads/list` | List / search leads (filter by contacted, replied, bounced, interest status) |
| high | `GET` | `/api/v2/leads/{id}` | Get one lead by id |
| high | `PATCH` | `/api/v2/leads/{id}` | Update a lead's fields or custom variables |
| high | `N/A` | `NOT AVAILABLE IN API v2` | Pause / resume an individual lead |
| high | `POST` | `/api/v2/leads/update-interest-status` | Set a lead's interest status (mark Meeting Booked / Not Interested / Wrong Person after screening) |
| high | `POST` | `/api/v2/leads/move` | Move leads between campaigns / lists (park or re-target) |
| high | `DELETE` | `/api/v2/leads` | Delete leads in bulk (remove non-fits from a campaign) |
| high | `GET` | `/api/v2/emails` | Fetch replies (the Unibox) - read inbound messages, bookings, out-of-offices |
| high | `GET` | `/api/v2/emails/{id}` | Get one email by id |
| high | `POST` | `/api/v2/emails/reply` | Send a reply into an existing thread (e.g. cancel a booking that is not a fit) |
| high | `GET` | `/api/v2/campaigns/analytics` | Campaign analytics - per-campaign totals (sent, opens, replies, bounces, leads) |
| high | `GET` | `/api/v2/campaigns/analytics/overview` | Campaign analytics overview - aggregate across campaigns incl. meetings booked |
| high | `GET` | `/api/v2/campaigns/analytics/daily` | Daily campaign analytics (time series for pacing / ramp monitoring) |
| high | `GET` | `/api/v2/campaigns/analytics/steps` | Per-step analytics (which of the 3 emails is producing replies) |
| high | `GET` | `/api/v2/campaigns/{id}/sending-status` | Diagnose why a campaign is not sending or is sending slowly |
| high | `POST` | `/api/v2/webhooks` | Subscribe to real-time events instead of polling (reply_received, bounce, meeting booked) |
| high | `POST` | `/api/v2/block-lists-entries` | Blocklist an address or domain (hard suppression, workspace-wide) |
| high | `POST` | `/api/v2/email-verification` | Verify an email address before sending |
| high | `GET` | `/api/v2/background-jobs/{id}` | Poll an async background job (lead move, import) |
| high | `POST` | `/api/v2/api-keys` | Create an API key with scopes |

**Rate limits**

> Source: https://developer.instantly.ai/getting-started/rate-limit (re-read
> this session) plus per-operation descriptions grepped out of the live OpenAPI
> spec.  GLOBAL (verbatim): "No more than 100 requests per second" and "No more
> than 6,000 requests per minute". "Your requests will be blocked if you reach
> ANY of the limits above." And: "The rate limit is shared between API v2 and
> API v1, and it applies to the entire Workspace, even if it's using multiple
> API keys."  PER-ENDPOINT OVERRIDES — the rate-limit page does NOT list these;
> they exist only in individual operation descriptions in the spec. Complete set
> found by grepping all 184 paths: - GET /api/v2/emails: 20 requests per MINUTE.
> The reply-reading endpoint, 300x tighter than the global minute limit. - POST
> /api/v2/emails/test: 10 requests per minute per workspace. - POST
> /api/v2/lead-labels/ai-reply-label: 500 requests per 30 days per workspace
> (testing endpoint only; live reply processing is unaffected). - DELETE
> /api/v2/domains/{domain}/forwarding: 10 per minute or 60 per hour. - POST

**Pricing**

> Source: https://instantly.ai/pricing raw HTML fetched and parsed 2026-08-30,
> plus https://help.instantly.ai/en/articles/10432807-api-v2.  PRICING
> CORRECTION — HYPERGROWTH IS $97/mo, NOT $358. The previous report could not
> resolve this and guessed. Resolved: the pricing page renders plan data twice.
> Its detailed plan cards and feature-comparison table say Growth $47/mo,
> Hypergrowth $97/mo, Light Speed $358/mo; the annual cards say $37.60, $77.60,
> $286.30. A separate marketing carousel on the same page mis-pairs prices one
> tier down, printing "Outreach Hypergrowth Plan $358/mo" — that carousel is the
> scrape artifact that produced the earlier $358 figure. The detail cards are
> authoritative.  OUTREACH-ONLY (sending) plans, monthly / annual-per-month: -
> Growth: $47 / $37.60 — 5,000 emails/mo, 1,000 uploaded contacts, unlimited
> email accounts, unlimited warmup, chat support - Hypergrowth: $97 / $77.60 —
> 25,000 uploaded contacts; emails listed as 125,000/mo on the monthly card but
> 100,000/mo on both the annual card and the feature-comparison table (vendor's
> own inconsistency, unresolved) - Light Speed: $358 / $286.30 — 500,000
> emails/mo, 100,000 uploaded contacts, SISR (Server & IP Sharding and Rotation)
> dedicated/private IP blocks - Enterprise: custom  CREDITS / LEAD DATABASE
> (separate subscription; needed for SuperSearch enrichment and Instantly's own
> verification) — CORRECTED: Growth Credits $47/mo ($37.60 annual, 1,500-2,000
> credits, 450M+ B2B database); Supersonic $97/mo ($87.30 annual, 5,000-7,500

**Gotchas**

- ADVERSARIAL-REVIEW CHANGELOG — what this pass changed and why. Every endpoint in the prior report exists; none was invented and none was deleted. All 184 paths, request schemas, response schemas and enums below were re- verified by downloading https://api.instantly.ai/openapi/api_v2.json (4.2 MB, OpenAPI 3.1.0, info.version 2.0.0) and parsing it locally, not by reading rendered doc pages. Corrections made: (1) POST /emails/reply body key is `reply_to_uuid`, not `reyply_to_uuid` — the prior requestExample would 400 on every call; (2) POST /leads/update-interest-status returns 202 with a background-job message, not a 200 ack — it is asynchronous; (3) GET /campaigns/{id}/sending-status returns {diagnostics,summary} and the always- present fields are nested under diagnostics, not top-level; (4) Hypergrowth is $97/mo, not $358 — resolved from the pricing page's raw markup; (5) Supersonic Cred
- THE REPLY FIELD IS `reply_to_uuid` — SPELLED CORRECTLY. The misspelling `reyply_to_uuid` occurs exactly twice in the entire spec, both inside the endpoint's prose description, and never in the JSON Schema the server validates against. The schema's required list is ['reply_to_uuid','eaccount','subject','body']. Two independent corroborations: the migration guide row for /unibox/reply says 'Reply with reply_to_uuid in body', and the webhook-events guide documents the payload field email_id as 'The ID of the email (reply_to_uuid)'. Do not code the typo and do not 'try both spellings' — the misspelled key is rejected by additionalProperties handling and, more importantly, the required key would then be missing.
- POST /api/v2/leads/update-interest-status IS ASYNCHRONOUS. It returns HTTP 202 with {message:'Lead interest status update background job submitted'}, not 200. An adapter that asserts status===200 fails on the happy path, and one that reads the lead immediately after may still see the old value. There is no background-job id in the response to poll — re-read the lead if you need confirmation.
- GET /api/v2/campaigns/{id}/sending-status IS NESTED. The response is {diagnostics: object|null, summary: object|null}, and campaign_id / last_updated / status / issue_tracking live inside `diagnostics`. Reading resp.status yields undefined, which most code will treat as 'no problem'. Also takes a with_ai_summary query param (default false) that populates `summary`.
- NO PER-LEAD PAUSE EXISTS — re-confirmed by enumerating all 184 paths. There is no /api/v2/leads/{id}/pause. Lead.status carries the value 2='Paused' but the field is readOnly:true, and PATCH /leads/{id} sets additionalProperties:false with an 11-key whitelist that has no status. To stop one person: delete the lead, move them to a parking list, blocklist the address, or set a terminal interest status. Any adapter method named pause_lead() must be implemented as one of those and documented as one-way.
- campaign_id vs campaign vs id — three names for the same concept. POST /leads/add uses `campaign_id`. POST /leads (single) uses `campaign`. POST /leads/list uses `campaign`. POST /leads/move uses `campaign` for the source and `to_campaign_id` for the destination. DELETE /leads uses `campaign_id`. GET /campaigns/analytics and /analytics/overview use `id` and `ids`. GET /campaigns/analytics/daily and /steps use `campaign_id`. Normalize this in one place — it is the single most likely source of silent failures.
- POST /api/v2/leads/move: `ids` is a FILTER, not a selector. Verbatim: 'When using this parameter, you must provide either campaign or list_id to specify which campaign or list to filter the leads from. This parameter acts as a filter within the specified campaign or list, not as a standalone way to select leads.' Sending only {ids, to_campaign_id} will not do what you expect. Also check copy_leads and reset_interest_status, which change the operation's semantics.
- DELETE /api/v2/leads deletes EVERYTHING MATCHING when `limit` is omitted: 'If not specified, all matching leads will be deleted.' The schema requires campaign_id or list_id via anyOf, and limit maxes at 10000. Always pass an explicit limit in an adapter.
- Lead item schemas reject unknown keys: additionalProperties:false on both the /leads/add item schema and PATCH /leads/{id}. Any enrichment field you carry (linkedin_url, icp_score, source, verifier_result) MUST go inside custom_variables, whose values must be scalar — string, number, boolean or null. Nested objects and arrays are rejected. Note the read/write asymmetry: you WRITE `custom_variables` and READ the same data back as `payload` (readOnly on the Lead schema).
- A created campaign starts in Draft (status 0) and sends nothing. POST /api/v2/campaigns/{id}/activate is a separate call. Neither /activate nor /pause declares a requestBody — id is the only parameter — and both return the full Campaign object, not a status envelope.
- sequences is an array but only sequences[0] is read, verbatim from the spec. Put all three steps in sequences[0].steps. Each step REQUIRES ['type','delay','variants'] — so you must send `delay` on the last step even though it means 'the delay before the NEXT email' and is therefore semantically irrelevant there. pre_delay/pre_delay_unit are explicitly 'ignored for regular campaigns' (subsequences only). type has exactly one legal value, 'email'.
- campaign_schedule.timezone is a CLOSED ENUM of 102 strings, not free-form IANA. Confirmed present: America/Chicago, America/Creston, Asia/Rangoon, Etc/GMT+12, Europe/Helsinki. The list is idiosyncratic and omits many common zones — validate against the enum at build time or campaign creation will 400.
- schedule.days keys are '0'-'6' with minProperties 1, BUT the spec carries no description stating which day is 0. The prior report asserted 0=Sunday as fact; that is the conventional reading and matches the schema's own example (0,1,2,3,4 true and 5,6 false, i.e. a Sun-Thu or Mon-Fri work week depending on convention), but it is NOT documented. Verify empirically on a throwaway campaign before trusting your send window.
- GET /api/v2/emails is capped at 20 requests per MINUTE while the global limit is 6,000/minute, and that cap appears only in the operation's own description, not on the rate-limit page. Build reply-reading on webhooks (reply_received / lead_meeting_booked / email_bounced) and use /emails only for reconciliation sweeps.

**Terms and account risk**

> Source: https://instantly.ai/terms, fetched and text-searched this session.
> FAVOURABLE, WITH A NARROWER SCOPE THAN PREVIOUSLY REPORTED. The defined term
> is "Permitted Purpose" (§1.10), not "permitted use", and the full sentence
> matters: "Subscriber's business use of the Instantly Service to manage and
> conduct Subscriber's OWN direct business-to-business (B2B) sales, marketing,
> recruiting, and business development activities of Subscriber, and expressly
> excludes any Data Resale Activity." Recruiting is named. But "Subscriber's
> own" is doing work — see risk 3.  RISKS YOU CARRY: 1. Consent and list
> sourcing are yours. §6.2: "Subscriber is solely responsible for any and all
> obligations with respect to the accuracy, quality and legality of Subscriber
> Data, including lead lists from third parties. Subscriber will obtain all
> third party licenses, consents and permissions needed for Instantly to
> receive, use and Process the Subscriber Data." Instantly obtains no consents
> on your behalf. CORRECTION: the previous report quoted "Subscriber is solely

**Verdict**

> RECOMMEND, with one architectural caveat, one plan warning, and three
> corrections that would have broken the build.  VERIFICATION STATUS: every
> endpoint in the reviewed report exists. I downloaded and parsed the live
> OpenAPI 3.1.0 document (184 paths) rather than reading rendered doc pages, and
> confirmed method, path, auth, required fields, full property lists, enums and
> response schemas for all 25 entries. Nothing was invented; nothing needed
> deleting. Three previously hedged entries (/leads/move, DELETE /leads, /block-
> lists-entries) are now fully specified. What did need fixing were four field-
> level errors and two pricing errors, listed below.  THE THREE FIXES THAT
> MATTER BEFORE ANYONE WRITES CODE: 1. The reply endpoint's field is
> `reply_to_uuid`. The prior report propagated a typo (`reyply_to_uuid`) that
> exists only in the vendor's prose, never in the schema. Coding it would 400
> the entire cancel-a-booking path — the one flow the spec was written for. 2.
> POST /leads/update-interest-status returns 202 and queues a background job.
> Code that asserts 200, or that reads the lead back immediately, is wrong. 3.
> GET /campaigns/{id}/sending-status nests its fields under `diagnostics`.
> Reading resp.status returns undefined, which reads as healthy — the exact
> failure mode a safety monitor must not have.  WHY IT STILL FITS: Instantly v2
> covers the sending half of the pipeline end to end. Campaign creation takes
> the full 3-step sequence, schedule, timezone, sending-account list and daily
> cap in one POST with only two required fields. Lead ingestion takes 1,000 at a
> time with arbitrary scalar custom variables — exactly how you inject a per-

---

## Smartlead.ai

- **Category:** send
- **Base URL:** https://server.smartlead.ai/api/v1
- **Docs:** https://api.smartlead.ai/ (index: https://api.smartlead.ai/llms.txt) and https://helpcenter.smartlead.ai/en/articles/125-full-api-documentation

**Auth**

> ?api_key=<key> as a query parameter on every request. No Authorization header
> exists. CORRECTION vs prior report: api.smartlead.ai/authentication states the
> key may ALSO be sent inside the JSON request body ("api_key": "...") for
> POST/PATCH calls, with the query param only "recommended". Use the body form
> on writes to keep the key out of access logs. Key from app.smartlead.ai ->
> Settings -> API Keys.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `POST` | `/campaigns/create` | Create a campaign (returns the campaign id everything else hangs off) |
| high | `POST` | `/campaigns/{campaign_id}/sequences` | Save the 3-step email sequence (job description + booking link) |
| high | `POST` | `/campaigns/{campaign_id}/leads` | Add enriched+verified leads to the campaign |
| high | `GET` | `/campaigns/{campaign_id}/statistics` | Campaign engagement counts per sequence step (NOT per-lead) |
| medium | `GET` | `/campaigns/{campaign_id}/leads-statistics` | Per-lead statistics with pagination (candidate reply sweep) |
| high | `GET` | `/campaigns/{campaign_id}/analytics` | Top-level campaign analytics rollup |
| high | `GET` | `/campaigns/{campaign_id}/analytics-by-date` | Analytics filtered to a date range |
| high | `GET` | `/campaigns/{campaign_id}/leads/{lead_id}/message-history` | Read the full email thread for one lead |
| high | `POST` | `/campaigns/{campaign_id}/reply-email-thread` | Reply inside an existing campaign thread (preserves sending account) |
| medium | `POST` | `/webhook/create` | Register a webhook so replies push to you instead of being polled |
| medium | `POST` | `/campaigns/{campaign_id}/schedule` | Set the sending schedule |
| medium | `POST` | `/campaigns/{campaign_id}/settings` | Set tracking, stop conditions, bounce autopause and domain rate limit |
| medium | `PATCH` | `/campaigns/{campaign_id}/status` | Start / pause / stop the campaign |
| high | `POST` | `/campaigns/{campaign_id}/email-accounts` | Attach the dedicated-domain sender mailboxes to the campaign |
| medium | `GET` | `/campaigns/{campaign_id}/leads` | List campaign leads, filterable by status (reply sweep / reconciliation) |
| medium | `PATCH` | `/campaigns/{campaign_id}/leads/{lead_id}/status` | Update a lead's status (mark not-a-fit after screening) |
| high | `GET` | `/leads/` | Look up a lead globally by email address (dedupe against prior roles) |
| high | `GET` | `/campaigns/` | List all campaigns |

**Rate limits**

> Two vendor sources, still conflicting, but one prior-report claim is now
> corrected. api.smartlead.ai/guides/rate-limits IS a genuine page (H1 "Rate
> Limits Guide") -- the prior report listed it among fetches that returned the
> fallback page; that was wrong. It states limits apply "to your API key across
> all endpoints combined": Standard 60 req/min, 1,000 req/hour, 10 req/sec
> burst; Pro 120 req/min, 3,000 req/hour, 20 req/sec burst; Enterprise custom.
> 429 body: {"error":{"code":"RATE_LIMIT_EXCEEDED","message":"Too many requests.
> Please retry after 30 seconds.","retry_after":30}}. Headers: X-RateLimit-
> Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After. CAVEAT ADDED:
> the tier names on that page (Standard / Pro / Enterprise) do not match any
> plan Smartlead actually sells (Base / Pro / Unlimited Smart / Unlimited
> Prime), so the mapping from your subscription to a row is undefined. Meanwhile
> helpcenter article 125 says only "Rate limits vary by subscription plan.
> Please contact customer support," with no numbers. Treat the table as soft:

**Pricing**

> CONFIRMED UNCHANGED against https://www.smartlead.ai/pricing this session.
> Four flat plans, monthly: Base $39 (6,000 sends/mo, 2,000 contacts, API access
> NO); Pro $94 (90,000 sends, 30,000 contacts, API access NO); Unlimited Smart
> $174 (150,000 sends, unlimited contacts, API access YES); Unlimited Prime $379
> (500,000 sends, unlimited contacts, API access YES). Annual billing ~17% off:
> $32.50 / $78.30 / $144.50 / $314.60 per month billed yearly. The pricing page
> groups the capability as "API & Webhooks" and includes it only in the two
> Unlimited tiers -- so the plan gate covers webhooks as well as the REST API,
> which matters because the corrected reply-detection design depends on
> webhooks. Verified prospect-email credits (2,000 / 30,000 / 50,000 / 170,000)
> and unlimited email accounts plus warmup on all plans were reported previously
> and were not contradicted, but the live page I read surfaced sends and
> contacts only -- treat the verification-credit figures as one source, not two.
> Third-party roundups add agency white-label workspaces at +$29/client/month,
> and note mailboxes, domains and verification credits are billed outside
> Smartlead and often exceed the subscription past single-digit inboxes.

**Gotchas**

- CHANGED -- CAMPAIGN STATUS: the prior report said POST {"status":"START"}. No vendor source anywhere uses START. Three vendor sources give PATCH /campaigns/{id}/status with {"status":"ACTIVE"}; the slug the prior report checked (/reference/update-campaign-status) is the fallback page. Corrected to PATCH + ACTIVE, medium confidence, POST as fallback. The prior 'you write START but read ACTIVE' gotcha is deleted -- write and read vocabularies match.
- CHANGED -- SCHEDULE BODY: the prior example was flat with days_of_the_week, max_new_leads_per_day and schedule_start_time. The vendor reference page shows the body NESTED under a `schedule` object with `days`, and none of those three fields. Corrected. Consequence: your 15-40/day throttle field is UNCONFIRMED -- max_new_leads_per_day appears only on a guides page and a third-party spec, is absent from the schedule reference schema, and is read back under a different name (max_leads_per_day). Verify it live before the first send; this is the top account-safety risk.
- CHANGED -- INVENTED ENUM VALUE: the prior report sent stop_lead_settings="REPLY_TO_AN_EMAIL". The confirmed enum is {CLICK_ON_A_LINK, OPEN_AN_EMAIL} only. Removed. track_settings is now confirmed as {DONT_TRACK_EMAIL_OPEN, DONT_TRACK_LINK_CLICK, DONT_TRACK_REPLY_TO_AN_EMAIL}. Stop-on-reply is not a stop_lead_settings option -- confirm that behaviour live rather than assuming a field sets it.
- CHANGED -- WEBHOOK PATH: the prior report recommended POST /campaigns/{campaign_id}/webhooks. That path has zero vendor support and its reference slug is the fallback page. Two vendor pages agree on POST /webhook/create with {name, webhook_url, association_type, email_campaign_id, event_type_map, category_id_map}. Switched. Also deleted the claim that a `categories` array is required and must be non-empty -- the real field is the optional `category_id_map`.
- CHANGED -- STATISTICS IS NOT PER-LEAD: /campaigns/{id}/statistics returns aggregate counts keyed by sequence_number with no lead identifier. The prior report made it the primary reply-detection sweep; it cannot list who replied. Reply detection now hangs on the EMAIL_REPLY webhook, with /campaigns/{id}/leads?status= for reconciliation. A separate, newly found endpoint GET /campaigns/{id}/leads-statistics may be the per-lead surface, but its response example is empty.
- CHANGED -- seq_variants/variant_label: the prior report claimed variant_label was confirmed on the vendor site. It is not. /core/sequences shows seq_variants with {variant_id, subject, email_body, distribution}; variant_label, variant_distribution_type and winning_metric_property appear nowhere on vendor pages. The sequence example is now the flat form the reference page actually documents. Skip A/B for v1.
- CHANGED -- REPLY REQUIRED FIELDS: reply_message_id is OPTIONAL per the vendor page, not required. Only email_stats_id and email_body are required.
- BLOCKING GAP -- message-history does not document the ids the reply endpoint needs. The vendor message object is {id, subject, direction, sent_at, opened_at, received_at}: no stats_id, no message_id. /reply-email-thread requires email_stats_id. Nothing on the vendor site connects the two. Pin this with a live call before committing to the in-thread cancellation note; if the id is not there, the cancel loop has no documented input.
- CONFIRMED AND STILL THE BIGGEST TRAP -- THE DOCS SITE SERVES THE WRONG PAGE. Any unrecognised /reference/ slug returns the 'Get All Campaigns' page with HTTP 200 and no error. I verified this with a deliberate nonsense slug. Four slugs cited in the prior report resolve to it: update-campaign-status, add- webhook-to-campaign, fetch-all-leads-from-a-campaign, and a general one. Always check the H1 matches the endpoint you asked for.
- ADD-LEADS RESPONSE NOW HAS THREE COMPETING SHAPES, two of them from Smartlead itself: the api-reference page gives {success, added_count, skipped_count, lead_ids, message}; guides/lead-management gives {added_count, skipped_count, skipped_leads[]}; third-party code gives {ok, upload_count, total_leads, ...}. The prior report told you to trust the third. Do not trust any -- branch on present keys, default counters to 0.
- NEW AND USEFUL -- set settings.return_lead_ids=true on add-leads to get lead ids back on import, saving a lookup round-trip. Not in the prior report.
- NEW AND USEFUL -- webhook deliveries carry X-Smartlead-Signature (HMAC- SHA256 of the raw body, 'sha256=' prefixed), X-Request-Id for idempotency, and X-Webhook-Level. Verify the signature; your pipeline sends email off these payloads. Not in the prior report.
- SOFTENED -- 'numbers as strings': no vendor page shows quoted numerics; the campaign-list page shows plain JSON numbers. This came from third-party normalisation code only. Still coerce defensively, but do not treat it as a documented behaviour.
- CORRECTED -- the rate-limits guide is a real page, not a fallback. Its numbers are usable but its tier names (Standard/Pro/Enterprise) match no plan Smartlead sells, and helpcenter refuses to give numbers at all.

**Terms and account risk**

> Unchanged in substance from the prior report; I did not read Smartlead's Terms
> of Service or AUP directly in this session either, so this remains
> orientation, not a legal reading. Smartlead is a sending platform only -- no
> LinkedIn scraping and no LinkedIn API surface, so that ToS exposure sits with
> your sourcing/enrichment vendor. What Smartlead carries: (1) acceptable-use
> terms prohibiting unsolicited bulk email and scraped or purchased lists sent
> without a lawful basis -- cold-mailing work addresses for recruiting needs a
> defensible legitimate-interest position, and GDPR applies to EU/UK recipients
> regardless of what Smartlead permits; (2) the operative risk is
> deliverability, not law -- bounce and complaint rates drive domain and mailbox
> reputation, which is why pre-send verification and the
> bounce_autopause_threshold / domain_level_rate_limit settings matter more than
> the contract; (3) 15-40/day from a dedicated warmed domain is normal behaviour
> and the correct posture. CONTRACTUAL GATE CONFIRMED on the live pricing page:

**Verdict**

> STILL RECOMMEND, but the prior report was more confident than the evidence
> supports and shipped at least four things that would have failed in code.
> Corrected: the status endpoint (POST/START -> PATCH/ACTIVE; START appears in
> no vendor source), the schedule body (flat -> nested under `schedule`, `days`
> not `days_of_the_week`), an invented stop_lead_settings enum value, and the
> webhook path (/campaigns/{id}/webhooks has zero vendor support -> POST
> /webhook/create). I also deleted the /leads/{lead_id}/category endpoint as
> unconfirmable and replaced it with the vendor-listed status/pause/unsubscribe
> routes. What got better: analytics-by-date, email-accounts and leads-by-email
> are now high confidence with real response shapes, the settings enums are
> pinned, and I found webhook HMAC signature verification plus
> settings.return_lead_ids, both missing before. The core five (create,
> sequences, leads, statistics, reply-thread) all sit on genuine vendor pages
> with matching H1s. Two things now stand between you and an adapter. (1) Reply
> detection has to be redesigned: /statistics returns aggregate counts per
> sequence step with no lead identifier, so it cannot tell you who replied --
> build on the EMAIL_REPLY webhook, verify its signature, and reconcile with
> /campaigns/{id}/leads?status=. Since webhooks are gated to the same $174+
> tiers as the API, that is not an optional extra. (2) One blocking unknown:
> /reply-email-thread requires email_stats_id, and the vendor's message-history
> response does not document any such field. Pin that with a live call before
> you promise the in-thread cancellation note. Budget floor is $174/mo plus

---

## Cal.com

- **Category:** booking
- **Base URL:** https://api.cal.com/v2
- **Docs:** https://cal.com/docs/api-reference/v2/introduction

**Auth**

> Authorization: Bearer <api_key> — CONFIRMED verbatim on the v2 introduction
> page: "Test mode secret keys have the prefix `cal_` and live mode secret keys
> have the prefix `cal_live_`". Keys are created in Cal.com account settings.
> PLUS a per-endpoint version header `cal-api-version: <YYYY-MM-DD>` whose value
> differs by endpoint (see per-endpoint notes); the event-types docs state
> verbatim "If not set to this value, the endpoint will default to an older
> version" — i.e. a wrong value degrades silently rather than erroring. NOTE:
> the cal-api-version header is NOT described on the introduction page itself;
> it is documented per-endpoint only. Platform/OAuth customers instead send
> `x-cal-client-id` + `x-cal-secret-key`, or a managed-user access token in the
> same Bearer header (access tokens valid 60 minutes, refresh tokens 1 year —
> confirmed on the introduction page). CAVEAT: the v1-v2-differences page's
> example uses a `cal_test_xxxxxx` key, while the introduction says test keys
> are prefixed `cal_`. If you build an environment guard on prefix detection,
> match on `cal_live_` for production and treat anything else as non-production,
> rather than matching the literal string `cal_`.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `GET` | `/v2/bookings` | List bookings with filters — the read-back step of the pipeline |
| high | `GET` | `/v2/bookings/{bookingUid}` | Get one booking by uid |
| high | `POST` | `/v2/bookings/{bookingUid}/cancel` | Cancel a booking with a cancellation reason |
| high | `POST` | `/v2/bookings` | Create a booking server-side (optional — pipeline normally uses the public booking link) |
| high | `POST` | `/v2/bookings/{bookingUid}/reschedule` | Reschedule a booking |
| high | `POST` | `/v2/webhooks` | Register a webhook subscription (BOOKING_CREATED etc.) |
| high | `POST` | `(your subscriberUrl)` | WEBHOOK DELIVERY — inbound BOOKING_CREATED POST to your subscriberUrl (this is the payload shape, not an endpoint you call) |
| high | `GET` | `/v2/event-types/{eventTypeId}` | Read an event type, including its current bookingFields (booking questions) |
| high | `POST` | `/v2/event-types` | Create the 10-minute screener event type with required booking questions |
| high | `PATCH` | `/v2/event-types/{eventTypeId}` | Add or change required booking questions on an existing event type |

**Rate limits**

> API key auth: 120 requests/minute, confirmed verbatim on the v2 introduction
> page, which adds "This can be increased to a reasonable amount, such as 200
> requests per minute" and "If you require a higher rate limit, such as 800
> requests per minute, it is possible, but it may involve extra charges." No
> auth: 120/minute. Platform paths: OAuth client credentials 500/min and managed
> user access token 500/min — the prior report held these at medium confidence;
> I confirmed them against calcom/cal.com issue #24963 ("docs: add rate limit
> section for v2", opened 2025-11-06 by supalarry, since closed), which
> enumerates all four figures. That issue's existence also confirms v2 rate-
> limit documentation is thin by the vendor's own admission. CORRECTED:
> X-RateLimit-Limit / X-RateLimit-Remaining / X-RateLimit-Reset response headers
> are NOT documented — there is no v2 rate-limits docs page (404) and the
> introduction states figures without describing headers. Do not depend on a
> remaining-quota header. Also note a conflicting 60 req/min figure circulating

**Pricing**

> CONFIRMED against https://cal.com/pricing (re-fetched 2026-08-30) — the prior
> report's figures were accurate and are unchanged. Free: $0, free forever, 1
> user, "Integrate with 100+ apps". Teams: "$12 per user/month" billed yearly
> (25% savings), adds "Remove Cal.com branding, Routing forms, Booking
> analytics, Custom APIs". Organizations: "$28 per user/month" billed yearly,
> adds unlimited sub-teams and "Additional APIs" plus all Teams features.
> Enterprise: custom, annual, adds dedicated onboarding and engineering support.
> Those are the ANNUAL-billing figures shown on the page; third-party trackers
> report month-to-month equivalents around $15 and $37 per user. CAVEAT
> CONFIRMED AND UNRESOLVED: the feature grid lists "Webhooks" as available
> across plans ("Send booking data instantly to your systems") but puts "Custom
> APIs" under Teams+, and the API docs describe API-key creation as a normal
> account setting with no stated plan gate. The page does not disambiguate
> whether a plain cal_live_ key against api.cal.com/v2 counts as "Custom APIs".
> Confirm with Cal.com sales before assuming Free suffices; budget Teams at
> minimum. The separate Cal.com Platform product (OAuth clients, managed users,
> embedded booking) is not on the public pricing page and is reported by third
> parties at roughly $299/mo — you do NOT need it for this pipeline, since a
> normal API key covers list/get/cancel/reschedule/webhooks.

**Gotchas**

- CHANGED THIS REVIEW — payloadTemplate on POST /v2/webhooks is OPTIONAL, not required. The prior report called it "marked REQUIRED in the input schema" and "a common 400 cause". The docs list exactly three required fields: active, subscriberUrl, triggers. Worse, the prior example sent payloadTemplate:"" — an empty template string is not equivalent to omitting the field and risks delivering an empty payload. Omit the field to get the default JSON payload.
- CHANGED THIS REVIEW — the claim "hidden fields still accept prefill (this is the documented UTM-tracking pattern)" is NOT documented anywhere I could find. I checked cal.com/help/bookings/prefill-fields, the mirrored help article, and cal.com/help/bookings/utm-tracking: none of them say hidden fields can be prefilled via URL, and the UTM page describes automatic capture, not hidden-field prefill. These were two unrelated features fused into one citation. The hidden `candidate-id` field is still the right design instinct — but PROVE IT FIRST with one manual booking through a real link before building the pipeline on it, because the entire read-back identity scheme depends on it.
- CHANGED THIS REVIEW — disableOnPrefill is a real, confirmed bookingFields property, but its documented meaning is narrower than the prior report implied. It makes a field read-only when its value is passed via the Platform Booker component's `defaultFormValues` prop. Whether it also locks a value arriving as a URL query param on a Cal.com-hosted booking page is NOT documented. Do not assume a candidate cannot edit your tracking value on the hosted link.
- CHANGED THIS REVIEW — POST /v2/bookings/{uid}/reschedule upgraded from medium to high. Fetched directly: path, POST method, and cal-api-version 2026-02-25 all confirmed, and it returns 201. It also requires `seatUid` in addition to `start` for SEATED bookings, which the prior report omitted. The prior report's "verify the version header before shipping" caveat is now resolved.
- CHANGED THIS REVIEW — POST /v2/bookings requires BOTH `start` and `attendee`. eventTypeId is optional (eventTypeSlug + username, teamSlug, or organizationSlug are alternatives). The prior report's example implied eventTypeId was the required identifier.
- CHANGED THIS REVIEW — the GET /v2/bookings `status` filter being SINGLE- VALUE-ONLY is unverified. The docs list the enum but say nothing about multiplicity. Test it; do not pre-build a two-call sweep on this assumption.
- CHANGED THIS REVIEW — X-RateLimit-Limit / X-RateLimit-Remaining / X-RateLimit-Reset are NOT documented. There is no rate-limits page at cal.com/docs/api-reference/v2/rate-limits (404) and the introduction page states figures without describing response headers. Write the client to back off on HTTP 429 using Retry-After if present, falling back to exponential backoff, and never to depend on a remaining-quota header being there.
- CHANGED THIS REVIEW — the cited GitHub issue is real and now closed: calcom/cal.com#24963 "docs: add rate limit section for v2", opened 2025-11-06 by supalarry. It confirms the platform figures the prior report only had at medium confidence: api key 120/min, OAuth client credentials 500/min, managed user access token 500/min, no-auth default 120/min. Caveat: a conflicting 60 req/min figure circulates in third-party summaries. The vendor introduction page says 120 — trust that, but build adaptive backoff rather than pacing hard against any published number.
- CHANGED THIS REVIEW — system/default booking fields do NOT all take the same properties. `location` accepts only `label`. Sending required/hidden on it may 400. title, notes, guests and rescheduleReason take the full set.
- CHANGED THIS REVIEW — key-prefix environment guards need care. The introduction says test keys are prefixed `cal_` and live keys `cal_live_`, but the v1-v2-differences page's example shows `cal_test_xxxxxx`. Match on `cal_live_` for production and treat everything else as non-production, rather than matching the literal `cal_`.
- CONFIRMED — cal-api-version is NOT one global constant. Verified per- endpoint on each vendor page this session: GET /v2/bookings = 2026-05-01; GET /v2/bookings/{uid}, POST /v2/bookings, POST /v2/bookings/{uid}/cancel, POST /v2/bookings/{uid}/reschedule = 2026-02-25; all /v2/event-types = 2024-06-14; POST /v2/webhooks documents no version header at all. Build a per-method version map.
- CONFIRMED — a wrong or stale cal-api-version does NOT error. Vendor wording on the event-types pages: "If not set to this value, the endpoint will default to an older version." You silently get a different request/response schema. Highest-risk failure mode in this integration: pin per call and assert on a response field you expect.
- CONFIRMED — schema names are not header values. Cancel and reschedule responses are typed BookingOutput_2024_08_13 etc. even though those endpoints take cal-api-version 2026-02-25. Do not send 2024-08-13 as a version header because you saw it in a schema name.
- CONFIRMED VERBATIM — API v1 is dead: "API v1 was shut down on April 8, 2026. All v1 endpoints have been removed." Any tutorial using ?apiKey= as a query param or DELETE /v1/bookings/{id}/cancel is dead code. Most Cal.com integration material on the open web now predates this.

**Terms and account risk**

> Unchanged from the prior report in substance; I did not re-fetch
> https://cal.com/terms this session, so treat the quoted clauses as carried
> forward rather than re-verified. Three clauses bear on this pipeline. (1)
> Anti-automation: the terms prohibit "any robot, spider, or other automatic
> device, process, or means to access Service for any purpose, including
> monitoring or copying any of the material on Service" — boilerplate written
> against web-app scraping, and in tension on its face with heavy programmatic
> use. The documented API with issued keys and published rate limits is the
> sanctioned channel: stay on api.cal.com/v2 and never drive the booking UI
> headlessly. (2) Anti-spam: prohibits using the service "To transmit, or
> procure the sending of, any advertising or promotional material, including any
> 'junk mail', 'chain letter,' 'spam,' or any other similar solicitation." Your
> cold email leaves your own domain, but the Cal.com-hosted booking link appears
> in every message, so complaints against the sequence are traceable back and

**Verdict**

> RECOMMEND for a 300-1000 person recruiting outbound run — the prior verdict
> survives adversarial review, with corrections. I fetched all ten endpoints
> against the vendor's own docs this session. Nine were confirmed exactly as
> reported: paths, methods, version headers, required fields, and response
> shapes. None had to be deleted as unconfirmable, and one (POST
> /v2/bookings/{uid}/reschedule) was UPGRADED from medium to high after direct
> verification, resolving the prior report's open item. That is an unusually
> clean report; the endpoint surface is real and the pipeline's needs are all
> first-class. THREE THINGS I HAD TO CORRECT, in order of blast radius. First,
> an invented citation: the claim that hidden booking fields accept URL prefill
> "(this is the documented UTM-tracking pattern)" is not documented on the
> prefill help page, its mirror, or the UTM page — two unrelated features were
> fused into one confident sentence. The entire candidate-id read-back
> architecture rests on it, so prove it with one manual booking through a real
> link before writing the adapter, and keep a fallback (distinct private booking
> links per candidate, or eventTypeId + afterCreatedAt reconciliation).
> Relatedly, disableOnPrefill is a real property but its documented semantics
> attach to the Platform Booker component's defaultFormValues prop, not to
> hosted-link URL params, so do not assume candidates cannot edit your tracking
> value. Second, a wrong required-field: POST /v2/webhooks marks payloadTemplate
> OPTIONAL, not required — only active, subscriberUrl and triggers are required,
> and the prior report's payloadTemplate:"" would have risked an empty delivered

---

## Calendly (API v2)

- **Category:** booking
- **Base URL:** https://api.calendly.com
- **Docs:** https://developer.calendly.com/api-docs — the reference is a Stoplight SPA and does not render for scrapers (re-confirmed 2026-08-30: WebFetch of developer.calendly.com pages returns only the landing shell). Machine-readable spec, re-downloaded and re-read in full this session (511 KB, HTTP 200): https://stoplight.io/api/v1/projects/calendly/api-docs/nodes/reference/calendly-api/openapi.yaml?fromExportButton=true&snapshotType=http_service&deref=optimizedBundle — openapi 3.0.0, info.version 2.0.0, title "Calendly API", single server https://api.calendly.com, project cHJqOjY4NTM, branch "production". Table of contents: https://stoplight.io/api/v1/projects/cHJqOjY4NTM/table-of-contents. Prose articles are individually retrievable as JSON (this is how to read them without a browser): https://stoplight.io/api/v1/projects/cHJqOjY4NTM/nodes/<slug> — e.g. .../nodes/edca8074633f8-api-rate-limits and .../nodes/ZG9jOjE1MDE3NzI-api-conventions both returned full markdown in the `data` field this session.

**Auth**

> Authorization: Bearer <PERSONAL_ACCESS_TOKEN> — CONFIRMED verbatim in the
> spec: components.securitySchemes.personal_access_token is {type: http, scheme:
> bearer, description: "Put the access token in the `Authorization: Bearer
> <TOKEN>` header"}. The oauth2 scheme carries the identical description, so the
> same header serves OAuth tokens (authorizationUrl
> https://auth.calendly.com/oauth/authorize, tokenUrl/refreshUrl
> https://auth.calendly.com/oauth/token). Every endpoint below lists `security:
> [oauth2, personal_access_token]`. Send Content-Type: application/json on
> POSTs. Token creation — CONFIRMED verbatim at
> https://developer.calendly.com/personal-access-tokens: log in > Integrations
> Page > "API & Webhooks" tile > "Get a token now" under Personal Access Tokens
> (or "Generate new token" under "Your personal access tokens") > name it >
> "Create Token" > "Copy token". Same page states tokens are unretrievable after
> creation: "we do not display or store them in your Calendly account. After
> generation, they're unretrievable." It also confirms you supply a scope list
> at creation time.

**Endpoints**

| Confidence | Method | Path | Purpose |
|---|---|---|---|
| high | `GET` | `/users/me` | Resolve the token owner's user URI and organization URI (needed as query params on nearly every other call, since Calendly identifies resources by URI |
| high | `GET` | `/scheduled_events` | List scheduled events (the bookings coming off the screener link) |
| high | `GET` | `/scheduled_events/{uuid}` | Fetch one scheduled event |
| high | `GET` | `/scheduled_events/{uuid}/invitees` | List invitees for an event, including their answers to the invitee questions (the screener questions) |
| high | `GET` | `/scheduled_events/{event_uuid}/invitees/{invitee_uuid}` | Fetch a single invitee |
| high | `POST` | `/scheduled_events/{uuid}/cancellation` | Cancel a scheduled event with a reason (the not-a-fit path) |
| high | `POST` | `/scheduling_links` | Create a single-use booking link, so each candidate's link is uniquely attributable and can only be booked once |
| high | `POST` | `/webhook_subscriptions` | Create a webhook subscription so bookings and cancellations push to you instead of being polled |
| high | `GET` | `/webhook_subscriptions` | List / get / delete webhook subscriptions |
| high | `POST` | `/invitees` | Book an invitee directly from your app (no redirect to Calendly UI) — 'Scheduling API' |

**Rate limits**

> Source: the Rate Limits article, retrieved this session as machine-readable
> markdown from
> https://stoplight.io/api/v1/projects/cHJqOjY4NTM/nodes/edca8074633f8-api-rate-
> limits (node id edca8074633f8 confirmed present in the live table of contents;
> rendered at https://developer.calendly.com/api-docs/edca8074633f8-api-rate-
> limits). CONFIRMED VERBATIM, every figure in the prior draft is correct. User-
> based, not app-based. Paid plans: 500 requests per user per minute. Free plan:
> 50 requests per user per minute. "These limits apply to both direct API calls
> and calls made through third-party integrations." "Rate limits are enforced
> per user." "Only 8 oauth tokens per user can be requested within a span of 1
> minute." Endpoint-specific, Create Event Invitee (POST /invitees): Trial 5
> requests per user per day; Paid non-Enterprise 10/user/min AND 50/user/hour
> AND 100/user/day (all three apply); Enterprise 500/user/min. On breach: HTTP
> 429 Too Many Requests with headers X-RateLimit-Limit (your ceiling),

**Pricing**

> Source: https://calendly.com/pricing, re-read 2026-08-30. Free: "Always free".
> Standard: "$10/seat/mo" billed monthly, with "Save 17%" on yearly. Teams:
> "$16/seat/mo" billed monthly, with "Save 20%" on yearly. Enterprise: "Starts
> at $15k/yr", "Starts at 50 seats", "Available in USD only". CORRECTION vs the
> prior draft, which hedged that "$10/$16 may be the annual-billed monthly rate
> — confirm at checkout": they are not. The page carries an explicit "Billed
> monthly" / "Billed yearly" toggle and $10/$16 are the MONTHLY-billed figures;
> yearly billing discounts them further (roughly $8.30/seat/mo Standard,
> $12.80/seat/mo Teams). Treat $10 and $16 as the ceiling, not the floor. Both
> Standard and Teams carry the note "Seats are required for users to connect
> calendars and host Calendly meetings - meeting invitees do not require a seat"
> — so only your recruiters need seats, not candidates. Calendly does not price
> the API separately: no API credits, no per-call charges, you pay for seats.
> Current plan lineup is Free / Standard / Teams / Enterprise; the legacy names
> Professional, Standard Plus and Teams Plus still appear in the help docs (and
> in the webhook plan-gate sentence) but are not sold on the pricing page —
> confirmed, they did not appear in this session's read. UNVERIFIED: the prior
> draft's FAQ figures "Payment via invoice is available on the Standard or Teams
> plan for $5,000 and Enterprise plan for $15,000" did not appear in the page
> content retrievable this session. Do not quote those numbers without re-

**Gotchas**

- VERIFICATION PASS, 2026-08-30 — what changed. All 10 endpoints in the prior draft were re-checked against the live Calendly OpenAPI document and all 10 SURVIVED: every path, method, operationId, required scope, path-param name, query-param set, request-body schema, success status code and response field list was confirmed. Nothing was invented and nothing was deleted. The corrections below are refinements and two genuine errors (pricing hedge, sort enum), plus one previously-blank section now filled in (POST /invitees body).
- CORRECTED — pricing. The prior draft hedged that $10/$16 per seat/mo "may be the annual-billed monthly rate." It is not: the pricing page shows a Billed monthly / Billed yearly toggle and $10 (Standard) / $16 (Teams) are the MONTHLY figures, with yearly saving a further 17% / 20%. $10 and $16 are the ceiling. Enterprise "Starts at $15k/yr" and "Starts at 50 seats" confirmed.
- CORRECTED — `sort` on GET /scheduled_events is not an enum. The prior draft wrote sort ('start_time:asc'|'start_time:desc') as if constrained. The schema is a bare `type: string`; the description says "comma-separated list of {field}:{direction} values. Supported fields are: start_time." Those two values work, but do not expect schema-level rejection of anything else.
- UNCONFIRMED — remove or re-check before relying on it. The prior draft's pricing-FAQ line about invoice payment at $5,000 (Standard/Teams) and $15,000 (Enterprise) did not appear in the page content retrievable this session. The $15k/yr Enterprise starting price IS confirmed; the invoice- threshold figures are not.
- UNCONFIRMED — the prior draft's claim that "tokens issued before scoped permissions retain full access" could not be verified this session. The scopes requirement itself IS confirmed (next item). Treat legacy-token grandfathering as unverified and assume you must select scopes.
- VENDOR SPEC IS SELF-INCONSISTENT ON WEBHOOK EVENTS — new finding. POST /webhook_subscriptions has a description table listing event_type.created / event_type.updated / event_type.deleted (auth scope event_types:read), but those three are ABSENT from the request body's `events` enum, which contains only: invitee.canceled, invitee.created, invitee_no_show.created, invitee_no_show.deleted, meeting_recap.created, meeting_recap.updated, meeting_recap.deleted, routing_form_submission.created, contact.created, contact.updated, contact.deleted. Code against the enum; test event_type.* before depending on it. Irrelevant to your pipeline, which only needs invitee.created and invitee.canceled.
- Scopes are explicit. Confirmed on https://developer.calendly.com/scopes: "for newly created OAuth apps and new Personal Access Tokens, no API access is granted until scopes are explicitly requested and approved." Each endpoint's reference page carries a Required scopes block. Select at minimum scheduled_events:read, scheduled_events:write, users:read; add scheduling_links:write and webhooks:read / webhooks:write if you use those paths.
- Per-endpoint scopes, each read off the endpoint's own description in the spec: /users/me = users:read; list+get events, list+get invitees = scheduled_events:read; cancel = scheduled_events:write; POST /invitees = scheduled_events:write; single-use links = scheduling_links:write; webhook create/delete = webhooks:write, webhook list/get = webhooks:read (invitee.* webhook events additionally need scheduled_events:read).
- Plan tier — API: available on EVERY plan including Free. Confirmed verbatim at https://calendly.com/help/calendly-api-overview: "Developers can make GET and POST requests to API endpoints on behalf of a Calendly user on any subscription plan." Only three endpoints are Enterprise-only: list activity log entries, delete invitee data, delete scheduled event data.
- Plan tier — WEBHOOKS and the Scheduling API: paid only. Confirmed verbatim on the same page: "For webhooks and Scheduling API endpoints, the Calendly user must have a paid subscription on the Professional, Standard, Standard Plus, Teams, Teams Plus, or Enterprise plan." Practically, Standard ($10/seat/mo, or less annually) is the cheapest current tier that gets webhooks. Everything your pipeline needs — list events, list invitees, cancel — works on Free; only the push path needs Standard.
- Resources are addressed by full URI, not by ID. Confirmed in the API Conventions article: "Instead of referencing unique resources by an ID ... we've decided that a more uniform approach ... is to use a Uniform Resource Identifier (URI)." Query params like `user` and `organization` want the whole URL, URL-encoded. Path params like {uuid} want only the last segment. Write one helper each way; mixing them up is the most common integration bug here.
- Invitee URIs are NESTED: "https://api.calendly.com/scheduled_events/{event_u uid}/invitees/{invitee_uuid}". To get the invitee uuid take the LAST path segment; the event uuid is third-from-last. Naive last-segment splitting that works for users and events will silently hand you the wrong id if you point it at an event URI expecting an invitee.
- Cancel is POST /scheduled_events/{uuid}/cancellation and returns 201, not DELETE and not 200. Verified there is no DELETE operation on /scheduled_events/{uuid} anywhere in the spec. The `reason` body is optional (requestBody required:false) but it is exactly the field you want (maxLength 10000).
- Cancelling a past or already-cancelled event returns 403, not 404. The DeleteScheduledEventError schema pins the message enum to exactly three values: 'You are not allowed to cancel this event', 'Event in the past', 'Event is already canceled', all under title 'Permission Denied'. Do not treat 403 as an auth failure and retry — parse the message and mark terminal.

**Terms and account risk**

> Re-read this session: https://calendly.com/legal/developer-policy (also the
> spec's own info.termsOfService URL). CONFIRMED: the policy prohibits using the
> API in connection with or to promote products/services constituting
> "unsolicited mass distribution of email ("spam")". Your pipeline is cold
> outbound at 300-2000 people per role with a Calendly link in the body — that
> is the shape of activity this clause names. It binds the API user, so the
> exposure is your Calendly account, not a rate limit. Also CONFIRMED:
> developers "must have an industry standard privacy policy in place that
> accurately describes the specifics of data usage and meets applicable legal
> and consent requirements"; stored data "must be stored within your system
> using strong encryption"; and third-party sharing is constrained —
> subcontracting processing to a third-party sub-processor requires prior
> written consent, with carve-outs only for legal compliance,
> merger/acquisition, and improving user experience/business needs. These bite

**Verdict**

> Recommend — and the recommendation is now stronger, because the prior draft
> survived adversarial verification almost intact. Every one of the 10 endpoints
> was re-confirmed against Calendly's live OpenAPI document this session: path,
> method, operationId, required scope, param names, body schema, success code
> and response fields. None were invented, none were stale, none needed
> deleting. Two real errors were fixed (the pricing hedge — $10/$16 are monthly-
> billed ceilings, not annual-equivalents; and `sort` on list-events is a free
> string, not an enum), two claims were demoted to unverified (the $5k/$15k
> invoice thresholds, and grandfathered pre-scopes tokens), one new vendor-side
> inconsistency was found (event_type.* webhook events appear in the docs table
> but not in the request-body enum), and the previously-blank POST /invitees
> body schema was filled in. Everything your pipeline needs is a first-class
> documented v2 endpoint: list events, list invitees with questions_and_answers,
> cancel with a reason. Auth is a single bearer header with a personal access
> token — no OAuth dance for an internal tool. Cost is a non-issue: the
> read/cancel path works even on Free, and Standard at $10/seat/mo or less buys
> webhooks so you can stop polling, with seats needed only for recruiters, not
> candidates. At 300-2000 candidates per role you are nowhere near the 500
> req/user/min ceiling. Four things to design around, none disqualifying: (1) no
> reschedule endpoint — surface Invitee.reschedule_url, or cancel and re-send;
> (2) no event_type filter on list events, so scope bookings with per-candidate
> single-use links or UTM params, which you want anyway for attribution; (3)

