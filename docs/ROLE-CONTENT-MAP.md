# Role keys, and where the rest of each role lives

Written 2026-08-30.

This repo sends the emails. The scorecard, the work simulation, the grading
rubric, the interview kit and the job-board rows for the same seat live in
the brain repo, under `projects/sunbird/hiring/`. Two halves of one thing.

Keep the two in step. A comp band, a title or a location that differs
between them will differ in front of a candidate.

---

## The map

| Role key here | Brain package | Title posted on job boards | Notes |
|---|---|---|---|
| `head-of-operations` | `hiring/roles/coo/` | Chief Operating Officer | **Same seat, two names.** `hiring-pack.md` calls it Head of Operations; the August 2026 job description calls it COO. Sought for 1.5 to 2 years, four failed attempts |
| `controller` | `hiring/roles/head-of-finance/` | Head of Finance | Posted as Head of Finance because that is what a startup finance lead searches for. Controller is kept as an alternate because it is what an accounting-trained candidate searches for |
| `engineer` | `hiring/roles/internal-tools-engineer/` | Internal Tools Engineer | Alternates posted: Founding Engineer, Full-stack Engineer (Operations), Automation Engineer |
| `chief-of-staff` | `hiring/roles/chief-of-staff/` | Chief of Staff | New here. Distinct from `ops-generalist`: senior, different pool, higher band |
| `quant-team-manager` | `hiring/roles/quant-team-manager/` | Quantitative Team Manager | New here. Widest title portfolio of any seat, by design |
| `ops-generalist` | `hiring/roles/operations-manager/` (partly) | Operations Manager | A bucket of about four mid-level seats, placed after the screener. The brain package covers the single senior floor-manager seat |
| `brand-and-funnel` | Wave 2 | Head of Brand and Funnel | JD added here. The scorecard and sim are Wave 2 in the brain pack |

---

## Titles to search versus titles to post

These are two different lists and merging them causes real problems.

- **Titles to search** are the `[icp].titles` arrays in this repo. They are
  wide on purpose. A good candidate for the engineer seat may currently be
  called a Platform Engineer, and we should write to them.
- **Titles to post** are in `brain:projects/sunbird/hiring/common/title-portfolio.md`.
  They are narrow on purpose, five per seat at most, and every one has to
  name a candidate population it reaches that the primary title does not.

Platform Engineer is a good search string and a bad posting, because as a
posting it attracts a specialism the seat does not want. Same for Solutions
Engineer and Technical Operations Engineer.

---

## What this repo does not do, deliberately

Cold email fits **one** of the three hiring problems.

| Problem | Seats | Channel |
|---|---|---|
| Senior and rare | the seven roles above | **This repo** |
| US and Canada volume, location-locked | 15 quant traders, 4 tech support | Job boards, campus, referrals. The block is platform access, not channel count |
| Offshore back-office | account executives, client support, document audit, intake | Local job boards and a local recruiter. Consent law forbids the alternative |

Do not point this pipeline at the volume seats. The compliance config
already blocks Canada, Poland and the EU at the country level, which is the
enforcement of the same rule.

---

## When something changes

| If you change | Also change |
|---|---|
| A comp band in `config/roles/*.toml` | `docs/COMP.md`, the brain scorecard header, the brain JD, and the job-feed row |
| A title in `[role].title` | `brain:hiring/common/title-portfolio.md` and the feed rows |
| A booking question in `[booking]` | `brain:hiring/roles/<slug>/sourcing.md` |
| A JD in `content/jd/` | The T1 version in `brain:hiring/roles/<slug>/jd.md`, which is the one that goes on job boards |

**The two JDs are not the same document and should not be merged.** The
version here is sent directly to a named person or hosted on our own careers
page, so it can use Peter's own framing. The version in the brain pack goes
onto LinkedIn and Indeed, where "stealth-stage" and "alternative markets" are
recorded removal triggers. `brain:hiring/sheet/compliance-notes.md` §3 has
both wordings side by side.
