# Compensation bands

**These are assumptions, not decisions.** Peter said to take a best guess and
keep moving (2026-08-30). Every band below says where it came from, so you can
see which are read off a document and which I made up.

Change one in the role file, or without touching git:

    # config/settings.toml
    [role_overrides.head-of-operations]
    comp = "$150,000 to $190,000 a year"

## The bands

| Role | Band | Source | Confidence |
|---|---|---|---|
| Head of Operations | $135,000 to $175,000 a year, plus equity | Read off the Q1 market map | **High** |
| Chief of Staff | $105,000 to $145,000 a year, plus equity | Read off the Q1 market map | **High** |
| Technical Program Manager | $90,000 to $125,000 a year, plus performance bonus | Read off the Q1 market map | **High** |
| Technical Support Specialist | $80,000 to $105,000, Philadelphia. Varies by city. | Read off the posting sheet | **High** |
| Controller | $140,000 to $180,000 a year | My guess | Medium |
| Engineer | $120,000 to $160,000 a year | My guess, anchored on the incumbent | Medium |
| Head of Brand and Funnel | $110,000 to $150,000 a year | My guess | Medium |
| Business Systems Lead | $95,000 to $130,000 a year | My guess. No source anywhere. | **Low** |
| Operations Manager | $70,000 to $95,000 a year | My guess | Medium |

## The reasoning, where I guessed

**Head of Operations.** Three figures in one document: $130k-$180k plus bonus,
$130k-$160k, and $135k-$175k base plus 0.5%-1.5% equity. I took the third,
because it is the most specific and the only one that names equity, and equity
is what makes this seat competitive against a bigger company's cash. A separate
line gives VP of Ops as $150k-$200k plus equity; if the answer to "which ops
title" turns out to be VP rather than Director, move up to that.

**Chief of Staff.** $105k-$145k plus 0.25%-0.75% equity, and $100k-$140k, in
the same document. Took the one with equity, same reasoning.

**Technical Program Manager.** One figure, no conflict. Used as written.

**Technical Support Specialist.** The posting sheet gives fourteen bands across
five public titles and seven cities. This band is the Philadelphia one for the
title the internal notes rate best. **The role config now carries a band per
search**, so a Detroit candidate is quoted the Detroit number. Do not collapse
these into one figure: quoting the wrong city's band to a candidate is a real
error and the opsec notes call it out.

**Engineer.** No band in any document. The incumbent is at about $8.6k a month,
which annualises to roughly $103k. The point of this hire is to stop one person
being a single point of failure, which means hiring at or above the incumbent,
not below. US senior full-stack with startup experience and daily AI tooling
runs $140k-$180k on a W2. This is a contractor with no benefits and no equity
stated, which normally pushes cash up, but the work is internal tooling rather
than consumer scale, which pulls it down. $120k-$160k sits between those and
clears the incumbent. If nobody good replies in three weeks, the number is the
first thing to move.

**Controller.** No band. This seat owns an accounting pass that has never been
done, a nominee tax structure, multi-entity and intercompany agreements, and
the excess funds exit rail. That is a controller with treasury and structuring
work at a fifty person company, not a bookkeeper. US market for that is
$140k-$180k, and the unusual nature of the business argues for the top of it
rather than the bottom.

**Head of Brand and Funnel.** No band. Owns the brand build, funnel v2, the
staffing brand, the VSL and the rejection experience for 30,000 applicants a
month. That is a head of growth with direct response depth: $110k-$150k US
remote.

**Business Systems Lead.** No band anywhere, and the weakest guess here. A
senior GoHighLevel, Airtable and Make builder is $95k-$130k in the US and
materially less offshore, and the source shows agencies were engaged across
LatAm, the US and Asia without deciding. If the answer to "onshore or offshore"
is offshore, this number is roughly double what it should be. The role is US
only in this machine because that is where cold email is lawful, so the US
number is the one in the file.

**Operations Manager.** No band for the seat as scoped. The target org chart
prices Ops Associates at about $4k a month, which is offshore pricing, and this
role is written as a US remote department head. $70k-$95k is the US mid-level
band for someone who has built a process and can name the number it moved.

## What would change these

1. **W2 or 1099.** Every posting in the sheet is 1099 or contract-to-hire. A
   1099 with no benefits should carry roughly 15 to 25 percent more cash than
   the equivalent W2 for the same person. The bands above are cash figures and
   do not have that uplift applied, so they read slightly low for contractors.
2. **Onshore or offshore.** Unanswered in the source. It halves several of
   these.
3. **Equity.** Two roles carry an equity range in the source. The others say
   nothing. If there is no equity, the cash has to be higher.
