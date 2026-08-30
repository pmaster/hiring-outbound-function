# Compensation, and where each number came from

Written 2026-08-30.

Every role config shipped with `comp = "NEEDS_PETER"`, and `doctor`
refuses to pass while a role that puts compensation in the email has
none. That is the correct gate: an invented number in a founder-sent
email to a senior operator is worse than no email.

The numbers below are **not invented**. They are Peter's own, recovered
from a recursive crawl of the hiring document tree on 2026-08-30, and
cross-checked against the seat-cost model in the brain repo
(`brain:projects/sunbird/pipeline/data/costs.csv`).

Full dated corpus map: `brain:projects/sunbird/hiring/evidence/CORPUS-MAP.md`.

---

## The source

**Hiring Sprint Q1**, Google Doc `1p1xSHI2tSil2ShIPY6zkw9IF0t2GIoAduO9dHEGqrrk`.
File created 2026-02-23, last modified 2026-08-24. The **content** dates
to February and March 2026: the lead tab is titled "March 2026" and holds
three finished Topgrading-format scorecards. The compensation figures sit
on the "Functions" tab and are Philadelphia-anchored for 2026.

Peter's own description of this doc, in the master doc: *"Q1 hiring
strategy doc on the top three roles - the most fleshed out, the most
relevant."*

---

## The bands

| Role key | Band used | Source | Confidence |
|---|---|---|---|
| `head-of-operations` | **$180,000 to $250,000 a year plus equity** | Hiring Sprint Q1, "COO" entry, Mar 2026. Model agrees: $20k/month = $240k | **High.** Peter's own number, and the model agrees |
| `controller` | **$130,000 to $180,000 a year** | Derived. Model says $10k/month = $120k. A live candidate (Greg) proposed $12.5k/month = $150k for the Finance Lead seat on 2026-08-19 | **Medium.** Bracketed by a model floor and a live candidate's own ask. The March doc's Finance tab is blank |
| `engineer` | **$5,000 to $10,000 a month** | The Internal Tools Engineer scorecard, v1.0, 2026-08-24. Stated verbatim | **High.** Current, written for this exact seat |
| `ops-generalist` | **$80,000 to $115,000 a year** | Hiring Sprint Q1, "Operations Manager (the site foreman)" entry, Mar 2026 | **High.** Matches the `seniority = "mid"` setting on this role |
| `brand-and-funnel` | **$110,000 to $150,000 a year** | Derived. Model says $8k/month = $96k for Brand and Funnel, $12k/month = $144k for Director of Marketing. This seat is scoped between them | **Low.** No figure exists in any document. This one genuinely needs Peter |

Two further bands from the same source, for seats this repo does not yet
carry:

| Seat | Band | Source |
|---|---|---|
| Chief of Staff | $105,000 to $145,000 base plus 0.25–0.75% equity | Hiring Sprint Q1, Mar 2026 |
| Quantitative Team Manager (Peter's "Quant PM") | $90,000 to $125,000 base plus performance bonuses | Hiring Sprint Q1, Mar 2026 |
| Quantitative Trader, individual contributor | $90,000+ a year, uncapped, "eat what you kill" | Hiring Sprint Q1, Mar 2026. Model agrees exactly: $7,511/month = $90k |

---

## What still needs Peter

1. **`brand-and-funnel`.** The only band with no documentary basis. Left
   at `status = "draft"` so `send` refuses it regardless.
2. **Whether these are contractor or employee rates.** Every role config
   says `employment = "contractor, full time, remote"`. The March 2026
   bands are written as salaries with equity, which reads as employee. A
   contractor rate and a salary are not the same number, and the
   difference is roughly the employer burden. **Nothing here is adjusted
   for that**, because the adjustment is a decision, not a calculation.
3. **Equity.** Three of the bands carry an equity component in the source.
   None of the role configs has a field for it. If equity is real, it
   belongs in the email, because it is a large part of why a senior
   operator takes an early-stage seat.

---

## Rules for changing a band

1. **Never write a number here that is not in a document or from Peter.**
   The gate exists for a reason.
2. **Change the band and the JD in the same commit.** They both appear in
   the same email.
3. **Say where the number came from**, in this file, with a date. A band
   with no provenance becomes an invented band within a month.
4. **A band that changes after emails have gone out needs a note in
   `docs/DECISIONS.md`**, because some candidate in the pipeline was told
   the old one.
