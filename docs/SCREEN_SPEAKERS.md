# Screen speakers: giving the people inside a terminal their own voice

## The problem

`Computer`, `Admin Terminal`, `Message File` and friends are not characters. They are *surfaces*.
Most of what they display was written by a person: a Shadowland BBS post, an email from a fixer, a
lab technician's journal, a job negotiation transcript. Voiced as one machine voice, the terminal
impersonates every one of them.

Scale, measured 2026-08-10:

| pack | container | lines | what is inside |
|---|---|---|---|
| dragonfall | `name_computer` | 401 | 181 BBS posts / 23 handles; 33 inbox mails + continuations; ~60 lines of `GUEST:`/`P_AMSEL:` transcript; the rest genuinely machine |
| hk | `name_computer` | 833 | 416 BBS posts / 128 handles; ~300 hub lines that are mail from named NPCs (Kindly Cheng, Is0bel, Bao JianJun, Gobbet, Gaichu…) |
| dragonfall | `name_adminterminal` 7, `name_messagefile` 2, `name_anonymousfileattachment` 1, `name_meetnmate…` 1, `name_digitalarchiveterminal` 27 | 38 | staff mail, Alice's letter, a dating profile |
| dragonfall | `name_note` 10, `name_diary` 2, `name_deaddropmessage` 4, `name_anonymousmessage` 2, `name_fromthedeskof…` 5, `name_harrowsmanifesto` 20 | 43 | letters signed `- Volker Stahl` / `- Owen`, a first-person diary, memos |
| dragonfall | `name_newsdayworldreport` 23, `name_shadowfrontindependentnewssource` 9 | 32 | news props that quote interviewees — the `quote_splits.json` case |
| hk | `name_admincomputer` | 18 | hotel staff mail |
| hk | `unattributed` | 520 | **108 of them carry `>>` screen text.** `apply_unattributed.py` is hardcoded to dms, so nothing has ever processed these |
| dms | `name_computer`, `name_personalcorrespondencearchive`, `name_voicelog`, `name_telestrianaccountingterminal`, `name_letter`, `name_datapad`, `name_newsnet`, `name_statemedicalboard` | 57 | lab journals, Telestrian mail — **out of scope, DMS is shipped** |

## Decisions (Martin, 2026-08-10)

1. **Hong Kong is re-extracted first.** It is still on the stale July extract; splitting 833 lines
   against attribution that is about to move would mean doing it twice.
2. **Recurring handles get their own voice; the long tail shares a pool.** HK has 128 handles, 60 of
   them with a single post. Handles with 3+ posts are cast individually; the rest draw from a small
   pool, assigned so two posters in one thread never share a voice.
3. **BBS voices must not consume the casting pool.** The lab's voice picker marks a voice "taken by
   <character>" from `picks.json`. Split-out BBS handles must be invisible to that, so the main cast
   can still be cast freely afterwards.
4. **Spoken text is the body only.** No `>>>>>[`, no `- Handle <10:55:01/…>`, no `>>From:` header.
   The handle is on screen; once each poster has their own voice the name is not needed as a cue.
   Martin's two existing Maelstrom edits are rewritten to match.
5. **DMS is not touched.** Findings are recorded here; no casting, no generation, no re-release.

## What already exists (and is reused, not rebuilt)

- `apply_reattributions.py` + `reattributions.json` — moves whole lines between characters, carries
  `takes.json` entries **and the audio on disk**, rewrites take `file` paths, creates a target
  character that does not exist yet (`to_name` / `to_portrait`), and is idempotent. This is exactly
  the whole-line move a split needs.
- `quote_splits.json` + `build_line_segments.py` — splits ONE line into `~cN` segments and writes a
  per-segment voice into `seg_overrides.json` tagged `source: "quote-split"`, rewriting only its own
  entries. This is exactly the in-line multi-speaker case (a BBS thread node with three posters, a
  `GUEST:`/`P_AMSEL:` negotiation).
- `spoken_rules.py` — the shared spoken-text rewriter used by both builders.
- `merges.json` / `character_merges.json` — precedent that a hand transform of `characters.json` is
  recorded in a sidecar and replayed after every re-extract.

Nothing here needs a new lab data model. A split is a **reattribution the extractor cannot derive**,
and the pack does not care: `build_voicepack.py` keys clips by `<convo>_<node>` and uses the
character only as the take bucket.

## Design

### New files

| file | role |
|---|---|
| `tools/screen_text.py` | parser: given a conversation, return the speaker structure inside it |
| `tools/screen_speakers_<game>.json` | **hand** file: conversation defaults, identities, aliases, keep-list |
| `tools/build_screen_splits.py <game>` | generator → `tools/screen_splits_<game>.json` + an unclassified report |
| `tools/screen_splits_<game>.json` | generated: `moves` (whole lines) + `inline` (multi-speaker nodes) |
| `tools/line_moves.py` | **the one** line/take/audio mover, lifted out of `apply_reattributions.py` |
| `tools/apply_screen_splits.py <game>` | applies `moves` through `line_moves.py` |
| `tools/screen_cast_<game>.json` | handle → `{voiceId, voiceName}` |
| `tools/apply_screen_cast.py <game>` | writes `picks.json`, never overwriting an existing pick |

There is exactly **one** implementation of the move. `apply_reattributions.py` already carries lines,
take records and the audio on disk between buckets, and creating a second copy of the repo's most
dangerous logic (a `shutil.move` loop with idempotency and take-key matching) to do the same job
would be a bug farm. The logic moves to `line_moves.py` and both scripts call it. Two real defects
get fixed on the way out:

- **`key#variant` take keys were silently left behind.** `move_takes()` matches `k in bases` or a
  `~cN` suffix, but a variant key is `<convo>_<node>#df_race_elf`, which is neither. Dragonfall has
  580 such keys today. None sit under `name_computer`, so this is latent rather than live — but a
  split-out character that later gets variant takes would lose them on the next move.
- **A missing audio file left `file` pointing at the old bucket**, so the take record kept a dead
  cross-bucket path instead of being reported.

Split-out people get ordinary `name_<slug>` ids. Not `bbs_<slug>`: the orphan sweep that cleans
`picks.json` filters on `k.startswith("name_")`, and a differently-prefixed id would leave a dead
pick behind forever.

### Parsing (`screen_text.py`)

Recognised forms, in order:

- **BBS post** — `>>>>>[ body ]<<<<<` followed by `- Handle <anything>`. Tolerant of: the leading
  `-` missing (HK `Tin Helmet <18:31:28/04-23-52>`), the closing `]` missing (HK `crumpeteer`),
  bodies spanning blank lines, several posts in one node, and a non-timestamp tag
  (`<Strikes Again!/Ha-Ha-Ha>`).
- **Mail header** — `>>*Sender*` / `>> *Sender*` / `>>From: Sender`, optionally followed by
  `>>to:` / `>>To:` / `>>Subject:` lines.
- **Mail continuation** — a node with no header, in the same conversation, whose node index follows
  a header node and which is not itself machine text. Attribution carries forward until the next
  header or a machine-text node breaks the run.
- **Sign-off** — trailing `-Name`, `- Name`, `Yours, Name`, `\m/ -ThOrvald`. Used to *confirm* a
  carried-forward attribution, and to strip the signature from the spoken text.
- **Transcript** — two or more `SPEAKER:` prefixes inside one node (`GUEST:`, `P_AMSEL:`).
- **Machine text** — a closed list of SHAPES, never "everything else": `>>` command/status lines,
  all-caps status blocks, ledgers (`WINNING BID: 1250¥`), menus, `No more posts in this thread.`

A node matching none of the above is **UNKNOWN and reported, never assumed to be machine**. Getting
that default backwards is the bug being fixed, not a tidy fallback: Dragonfall's
`525c7c176636614821003cf6_4` is unmarked first-person hotel-staff prose ("Paranoid son of a bitch…
New code is 1989") with no marker of any kind, and a catch-all would leave it in the robot voice
silently. 137 of that container's 401 lines carry no marker at all.

Unknowns are resolved a **conversation at a time** in the hand file rather than by teaching the
parser a regex per phrasing — a sewer pump console is machine top to bottom, a lab-notes terminal is
one technician's journal top to bottom.

### Identity resolution (`screen_speakers_<game>.json`)

The generator proposes; the hand file decides. It carries:

- `aliases`: `{"Malestrom": "Maelstrom"}` — a misspelling in the game data is the same person.
- `existing`: `{"Mettbach, Gunari": "name_gunarimettbach", "Kindly Cheng": "name_kindlycheng"}` —
  mail from a character the pack already has goes to **that** character and inherits their cast
  voice. Name matching is proposed automatically (surname-first, titles, `Dr.`) but written into the
  hand file so it is reviewable rather than re-derived every run.
- `keep`: `["WITHHELD", "SYSOP", "System Daemon"]` — handles that really are the machine, or
  deliberately anonymous, and stay with the container.
- `new`: `{"Tolstoi": {"id": "bbs_tolstoi", "gender": "male"}}` — handles that become characters.

New characters are created with `"screenSpeaker": "bbs"` on the record, which excludes them from
**every** surface that treats casting as a scarce pool — there are three, not one:

- `lab.html`'s voice-picker `taken` map;
- `lab.html`'s suggestion pills, which also filter `S.picks` to drop voices used elsewhere — 128
  screen speakers would otherwise strip the pills for every remaining HK character;
- `build_char_notes.py`'s `used_count`, which penalises a reused voice when generating suggestions.

The flag also drives a sidebar filter: `/api/state` ships the whole of `characters.json` (HK is
5.8 MB already) and ~128 permanently-portraitless, note-less entries would otherwise flood the cast
list and the "show only incomplete" filter.

**The flag does not make the voices free.** It hides them from the picker; the catalog is still
consumed. Dragonfall's cast used 148 English voices and has 69 left, which covers its 23 handles.
Hong Kong has 217 free only because **it has not been cast at all** — 2 of 235 characters — so its
main crew is cast BEFORE the BBS handles, and the handles get an explicit budget out of what is
left (Martin, 2026-08-10).

### Spoken text

What is spoken today for `527abf9e636134b83400302e_62` is:

```
[You all hear about the S-K team that got crisped a few hours ago? ...] - Clockwork 13:27:02/09-01-38
[At this point, who hasn't?] - Big Pharma 13:28:05/09-01-38
```

The brackets and the timestamps are read out loud. Nothing strips them: `mechanical()` →
`strip_angles()` only replaces the `<`/`>` characters, and `defaultSpoken()` (both the JS copy in
`lab.html` and the Python one in `lab/spoken.py`) removes `{{GM}}` spans and nothing else.

`build_spoken_overrides.py` gains one rule: for a line the parser recognises as a screen speaker's
words, the override is the **body only** — markers, header and signature removed — and is written
even when the line contains no `$()` variable.

The stripping lives in `spoken_rules.py` next to `strip_angles()` and must run **before** it:
`strip_angles()` destroys the `<timestamp>` that identifies a signature line.

Three layers shadow that override and all three have to be dealt with, or the rule changes nothing
for most of the corpus:

- **`tools/spoken_hand_rewrites_<game>.json` wins outright** (`build_spoken_overrides.py` checks it
  first and `continue`s). **129 of Dragonfall's 401 `name_computer` lines have an entry**, and they
  bake in exactly what is being removed: `_126` reads `"Mettbach, Gunari If you value new hardware
  coming into the Kreuzbasar…"`. Every hand rewrite for a split line is pruned.
- **`directed.json`** beats the override at generation time (`lab/spoken.py`'s `effective_text`
  resolves `text_edits > directed > raw`). 87 Dragonfall segments on these lines have one, so
  `build_directed.py` must be re-run — it is step 8 of the re-extract order and easy to skip in a
  partial run.
- **`text_edits.json`** wins over everything. 7 Dragonfall entries, including Martin's two Maelstrom
  lines, which are rewritten to the body-only form.

`spoken_overrides.json` is rebuilt wholesale per game, and nothing imports `spoken_rules.py` at
runtime, so the change is inert for DMS and Tyranny **until somebody re-runs the builder there**.
That is a delayed trap rather than safety: a DMS re-run would silently restate 57 shipped lines. The
screen-speaker stripping is therefore gated on the game being one this pass has surveyed.

### Stale takes

A take record stores `file / voiceId / stability / chars / ts` — no text and no hash of it. When a
line's spoken text changes, the old clip stays `selected`, `build_voicepack.py` only checks that the
file exists, and the pack ships audio of the old words. `audit_takes.py` compares the stored `chars`
against the audio duration; both come from the old generation, so a stale take is self-consistent
and passes.

Two consequences for this pass:

- `apply_screen_splits.py` **clears `selected`** on every line it moves and on every line whose
  spoken text the new rule changes. Dragonfall's `Computer` holds 322 selected takes, 211 of them on
  lines whose text carries screen markup; without this the pack would ship Microsoft David reading
  timestamps under a new character's name.
- Recommended follow-up (not in this pass): store a hash of the generated text on each take and have
  the builders flag a mismatch. That would also catch the two shipped DMS `they's` takes already
  recorded as needing regeneration.

### In-line multi-speaker nodes

`build_line_segments.py` reads `screen_splits_<game>.json`'s `inline` map alongside
`quote_splits.json`, through the same code path: the node becomes `~c0…~cN` segments and each gets
a `seg_overrides.json` entry. Tagged `source: "screen-split"` so the builder rewrites only its own.

These nodes stay with the container character — a line belongs to exactly one character, and these
have two or three authors. Dragonfall has 10 of them; **Hong Kong has none** (all 425 of its
signature nodes carry exactly one handle).

`split_quotes()` locates a span with `text.find(q)` against the spoken text and, when it misses,
prints a `WARN` and carries on — collapsing the node silently back to one voice, which is invisible
in the lab. Since the spans are generated from the *stripped* text, any change to the stripping rule
would break every one of them at once, so the builder asserts that every declared span was found.

### Casting

`screen_cast_<game>.json` maps handle → voice, applied with `setdefault` semantics so anything
Martin re-casts in the lab survives a re-run. Voice selection is by hand (mine), informed by each
handle's actual posts — gender cues, age, register — and constrained to voices not already cast in
that pack.

Dragonfall has 69 free English voices against 23 handles: all individual.

Hong Kong's handle counts (126 handles, 53 with 3+ posts, 49 with one) are measured on the **stale**
extract that decision 1 replaces, so they move. Its casting waits until the main crew is cast, and
then takes a named budget out of the remainder.

### Order of operations

Slots into the documented re-extract order, after step 3 (`merge_characters.py`):

```
3.  merge_characters.py <game>
3a. build_screen_splits.py <game>      # regenerate the split plan from the fresh extract
3b. apply_screen_splits.py <game>      # move lines + takes + audio, clear stale `selected`
3c. apply_screen_cast.py <game>        # fill in picks for split-out people
4.  (HK only) apply_hk_names.py
5.  build_spoken_overrides.py <game> ; build_line_segments.py <game>
6.  extras / loadscreens / epilogue
7.  extract_portraits_game.py ; build_char_notes_game.py <game>
8.  lab/tools/build_directed.py --game srr-<game>     # REQUIRED: directed.json beats the override
9.  lab/tools/build_dupes.py --game srr-<game>
```

Steps 8 and 9 are not optional here even though the split itself does not touch them: 87 Dragonfall
segments on these lines carry a `directed.json` entry that would otherwise keep generating the old,
un-stripped words.

## Cost

Casting is free. Generation is not, and is a separate, explicitly-approved step:

- Dragonfall's `Computer` is 319 selected SAPI David takes (local, free) plus 2 Magnific. Every line
  that moves to a person needs a Magnific take: ~181 BBS posts + ~33 mails ≈ 45k characters.
- Hong Kong's `Computer` has **zero** takes today. ~416 posts + ~300 mail lines.
- Machine lines that stay behind keep SAPI and are free to re-cut when their spoken text changes.

No generation happens in this pass.
