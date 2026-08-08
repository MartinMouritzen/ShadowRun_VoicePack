# Template-variable variants

Shadowrun authors a line once and shows it several ways. "Greetings, young `$(l.race)`." is one
node that displays as human, elf, dwarf, ork or troll; "`$(l.he)` is right" is one node that
displays as he or she. Before this existed the lab dodged those: `spoken_overrides.json` rewrote
the sentence so the word never had to be said, which is why an ork player never once heard the
word "ork".

Now the same node is generated once per value and the plugin plays the one that matches the
playthrough.

## What varies, and what never can

A variable is expandable only if its value set is **closed**:

| Variable | Values |
|---|---|
| `l.race`, `l.metatype` | human, elf, dwarf, ork, troll |
| `l.he/him/his/hisher/man/guy/sir/honorific/freund`, `s.he/him/his` | male, female |
| `scene.badfantasy` (Aljernon) | 10 race x gender words: elfling, she-ork, he-troll, madam... |
| `scene.CafeSpecial` | 7 drinks, read out of the scene blobs |
| `scene.str_RedOrGreen` | 2 |

`$(l.name)` is the player's typed name, and `$(scene.numUnreadMessages)` / `$(story.date_*)` are
counters and dates. Those have no closed set and keep their single generic take forever - the
rewrite layer still dodges them, exactly as before.

## How it is built

`build_line_segments.py` re-derives every affected line once per value, through the *same*
derivation the generic take uses, and writes `variants.json`:

```json
{"segments": {"<segKey>": {"axes": ["race"], "v": {"human": "...", "elf": "..."}}}}
```

Two deliberate choices:

- **Overrides are bypassed for these lines.** The override *is* the dodge, so honouring it would
  produce five identical clips that all avoid the word.
- **A segment whose text still holds an unbounded variable after substitution is dropped** and
  keeps its generic take. Bypassing the override also discarded whatever dodge it applied to
  `$(l.name)` in the same sentence, and voicing that would read the token aloud. 12 segments.

Set `SRR_CONTENT_PACKS` to the game's `ContentPacks` directory to pick up the scene-string sets;
without it the gender and metatype axes still work, since those are engine constants.

## How it is keyed

- **Dialogue** (`<convoId>_<node>`): variant clips are `<key>#<variantId>`, where the id is the
  axis values joined by `.` in axis order - `elf`, `m`, `m.elf`. The plugin tries most specific
  first and falls through to the plain key, which always exists.
- **Inspect** (`insp_<md5>`): keyed by the md5 of the **resolved** sentence. The plugin expands the
  raw text and hashes the result, so it needs to know nothing about which variable was involved.

## How the plugin picks

`Variants.cs` does not read the player object. It asks the game's own `ParseTextExpansion` to
expand `$(l.race)` and `$(l.he)` and uses whatever comes back, so the audio cannot disagree with
the words on screen. If that method is unreachable it logs a warning and every line falls back to
its generic clip - the behaviour the pack had before variants existed.

On first resolution the log says which variant is in force:

```
variants: this playthrough is 'f.elf'
```

If it says `(unresolved - using generic clips)`, the expander could not be called from where the
plugin asked, and no variant clips will play.

**The DLL only loads at game start.** Clips and the manifest hot-reload within ~2s, plugin code
does not - restart the game after installing a new `SRRVoices.dll`.
