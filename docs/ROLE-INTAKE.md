# Adding a role, or tightening one

Peter said more specifics on the roles are coming. This is what to do with
them, and what is actually needed.

## The short version

Everything about a seat lives in one file: `config/roles/<key>.toml`. Nothing
in the code knows about any particular role. Adding one is a copy, an edit and
a template.

## What is needed to define a role

Answer these eight. Everything else has a working default.

1. **Title, and how many seats.**
2. **The one line pitch.** What the person owns, in a sentence. It goes on the
   careers page and in the email.
3. **Comp.** A number or a band. This blocks the send, because step one puts
   it in the email.
4. **Titles to search for**, and the titles that look right but are wrong.
   The second list matters more than people expect: "Operations Coordinator"
   is not an operations leader, and without the exclusion it lands in the
   review queue every day.
5. **Company size band.** For Head of Operations it is 30 to 300, and the
   reason is written down: below 30 they never ran a department, above 300 the
   system already existed. Give the equivalent reason for a new seat, because
   it decides half the list.
6. **The three or four things that must be visible on the profile.** Not the
   job description. The things a person can see in thirty seconds. For Head of
   Operations it is: they built something that did not exist, they owned a
   whole function, and they stayed somewhere at least three years.
7. **The disqualifiers.** What makes you close the tab immediately.
8. **The four booking questions.** What you would ask before agreeing to a
   ten minute call.

If an answer is not known, write `NOT DECIDED` rather than guessing. The role
stays `status = "draft"` and refuses to send until it is filled in.

## Where each answer goes

| Answer | Where |
|---|---|
| 1, 2 | `[role]` title, seats, one_liner |
| 3 | `config/settings.toml`, under `[role_overrides.<key>]`. Not the role file, which is committed. |
| 4 | `[icp] titles` and `[icp] title_excludes`, plus the `title_match` signal |
| 5 | `[icp] company_headcount` and the `headcount_band` signal |
| 6 | one `[[signal]]` block each |
| 7 | `[[disqualifier]]` blocks, or a negative weight signal where it is a judgment call |
| 8 | `[booking] questions` |

## The steps

1. Copy the closest existing role file.

       cp config/roles/ops-generalist.toml config/roles/new-seat.toml

2. Edit it. Set `status = "draft"` until the comp and the description exist.
3. Copy the templates and rewrite them.

       cp -r templates/ops-generalist templates/new-seat

   Step one must contain `{{personal_note}}`. The render refuses without it.
4. Write `content/jd/new-seat.md` if the role needs a public page.
5. Check it loads and renders.

       python3 -m outbound roles
       python3 -m outbound doctor new-seat

6. Score an existing list against it to see whether the ICP does what you
   meant. This is the step people skip.

       python3 -m outbound import new-seat some-list.csv
       python3 -m outbound score  new-seat
       python3 -m outbound review new-seat

   Read the top ten and the bottom ten. If the top ten are not people you
   would write to, the signals are wrong, not the people. Change the weights
   and run `score new-seat --restage`.

## Tuning an ICP that is not working

| Symptom | Usually |
|---|---|
| The review queue is full of near misses | `auto_reject_below` is too low, or `title_excludes` is missing an obvious title |
| Good people are being auto rejected | A signal is doing too much work. Check `score_json` on one of them: `python3 -m outbound review <role> --json` |
| Every candidate scores about the same | The signals are all firing on everyone. Add one that actually discriminates, usually a regex on the profile text |
| Scores look right but replies are low | The ICP is fine and the copy or the personal note is not |

The per signal breakdown is stored with every candidate, so you can always ask
why a specific person got the score they got rather than arguing with a number.
