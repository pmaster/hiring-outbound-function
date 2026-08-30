# Architecture

For whoever maintains this. Read `README.md` first.

## The shape

    config/roles/*.toml ─┐
    config/settings.toml ┼─> config.py ──> Role, Settings
    .env ────────────────┘

    provider ──> profiles.py ──> score.py ──> db.py
                (normalise)     (rank)      (state)
                                              │
                                 compose.py <─┤
                                (render)      │
                                  │           │
                            compliance.py     │
                               (refuse)       │
                                  │           │
                                send ─────────┘
                                  │
                            replies.py, bookings.py
                                  │
                              report.py

`pipeline.py` is the only module that knows the order. Everything else does
one thing and does not import the pipeline.

## The rules that shaped it

**One TOML file is one seat.** The ICP, the scoring signals, the searches and
the screener questions all live together. Changing who we write to should
never mean changing code.

There are seven provider stages: search, enrich, verify, evaluate, send,
booking and replies. Every one has a `dryrun` or offline implementation,
which is why the whole thing runs with no keys. `evaluate` is the AI screen:
its `dryrun` reuses the heuristic score, and its `anthropic` adapter calls a
model to judge fit and draft the personal note.

**Providers know nothing about the pipeline.** An adapter takes a request and
returns a plain dict or list. `profiles.py` is the only place that maps a
vendor's field names to ours, so adding a provider means adding aliases there,
not teaching the scorer a new shape.

**Every step is idempotent.** These commands run on a cron. A half finished
run must never double send. `import` upserts on the normalised LinkedIn URL.
`queue` skips a candidate who already has that step. `send` selects only
`status = 'queued'` and marks each row as it goes.

**Guard rails raise.** `compliance.py` throws rather than logging a warning,
because a warning in a nightly job is a warning nobody reads.

**Unknown is a real answer.** `guess_country` returns an empty string rather
than a guess, and the geo gate refuses empty. Where being wrong is expensive
in only one direction, the missing value survives to the decision.

## The database

SQLite, one file, no server. `db.py` holds the schema as a single string plus
a small migration list. `CREATE TABLE IF NOT EXISTS` does not add a column to
an existing table, so every schema change needs a line in `Database.MIGRATIONS`
and a bump of `SCHEMA_VERSION`.

Tables: `candidates`, `emails`, `messages`, `bookings`, `suppression`,
`events`, `runs`, `send_log`.

The funnel is `candidates.stage`, ordered by the `STAGES` list. Terminal
stages are in `TERMINAL_STAGES`. Nothing walks a candidate backwards except by
hand.

Dedupe key is `(role_key, linkedin_key)` where `linkedin_key` is the
normalised profile URL. The same person in two roles is two rows on purpose:
they are two different pitches with two different notes.

## Scoring

`score.py` reads `[[signal]]` blocks and produces a number between 0 and 1
plus a per signal breakdown, which is stored as `score_json` and shown in the
review queue. Weights are relative and normalised by the sum of the positive
weights, so adding a signal does not require rebalancing the others. A
negative weight is a penalty, not a reject; `[[disqualifier]]` blocks are the
hard rejects.

Two matching rules worth knowing:

- `any_of` matches on word boundaries. Substring matching scored an
  "Operations Coordinator" as a COO, because "coordinator" contains "coo".
- `icp.title_excludes` is applied as a hard reject before anything else. It is
  a filter, not a comment.

A numeric signal with no data scores 0.5, not 0. Absence of evidence is not
evidence of absence, and zeroing it buries every thin profile.

## Adding a provider

1. Write `outbound/providers/<name>.py`. Implement one of the five protocols
   in `providers/__init__.py`.
2. Call `httpjson.get` and `httpjson.post` through the module, not by
   importing the functions. The tests patch the module.
3. `register("<stage>", "<name>")(YourClass)` at the bottom.
4. Add the module to the import list in `providers.build`.
5. Add its key to `.env.example`.
6. Add a test in `tests/test_providers.py` with the fake transport. Assert the
   auth header, the path and the field names. Those are what cost money to get
   wrong on a live run.

## Adding a role

1. Copy an existing `config/roles/*.toml`.
2. Put the screener questions under `[booking] questions`. A bare
   `booking_questions` key after a table gets absorbed into that table by TOML,
   which is how the first version shipped with no questions at all.
3. Create `templates/<template_dir>/step-1.md` through `step-3.md`.
4. Write `content/jd/<key>.md` if the role needs a public page.
5. Leave `status = "draft"` until the comp and the description are settled.
   Draft roles score but refuse to send.

## Tests

    python3 -m unittest discover -s tests -v

- `test_outbound.py` — util, profiles, scoring, database, compliance, compose,
  pipeline, bookings, pages, config.
- `test_providers.py` — every adapter against a fake transport.
- `test_replies.py` — reply, bounce and unsubscribe classification.
- `test_cli.py` — every command runs and every error is a message.

**No test may reach the network.** Every test module sets `OUTBOUND_OFFLINE`,
which makes an unmocked HTTP call fail immediately and say so, rather than
hanging, costing money, or passing for the wrong reason. It caught three tests
the moment it was added. The transport tests opt out explicitly, because they
exercise the transport with `urlopen` mocked.

Several of these tests exist because they caught something real: the T1 disclosure check
caught a public page saying "gambling experience not required"; the schema
migration test exists because the first schema change would have broken an
existing database; and the Instantly passthrough check exists because a
sequencer silently sends its own copy rather than yours.
