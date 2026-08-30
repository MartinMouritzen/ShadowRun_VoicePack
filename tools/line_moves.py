"""Moving a line from one character to another, with everything that has to follow it.

The only implementation. `apply_reattributions.py` (the extractor put the line on the wrong speaker)
and `apply_screen_splits.py` (the line was never the terminal's to begin with) do the same physical
job, and a second copy of a `shutil.move` loop with idempotency and take-key matching would be a bug
farm.

takes.json is bucketed by character id and build_voicepack.py looks a line up under its OWNING
character, so a line that moves without its takes silently loses its audio. The audio moves on disk
too (app/audio/<game>/<charId>/) and the 'file' path in the take record is rewritten to match. GM
segments (~gN) live under 'narrator' and never move; character segments (~cN) do.
"""
import os
import shutil


def resolve_merge_target(char_id, merges):
    """Return the live end of a recorded character-merge chain.

    Correction files are intentionally durable: a reattribution may still name the identity that
    existed in the raw extract even after ``merge_characters.py`` folded it into the canonical
    cast entry.  Every writer must resolve that historical id before creating or looking up a
    destination, otherwise re-running an older correction resurrects the alias that the merge
    removed.  A cycle is invalid data; failing loudly is safer than choosing one member and
    splitting the character again.
    """
    cur = char_id
    seen = []
    while cur in merges:
        if cur in seen:
            chain = " -> ".join(seen + [cur])
            raise ValueError(f"character merge cycle: {chain}")
        seen.append(cur)
        cur = merges[cur]
    return cur


def take_keys(bucket, convo, nodes):
    """Every take key in `bucket` that belongs to these nodes of this conversation.

    Four shapes exist, and all four have to be caught:
        <convo>_<node>                 the plain line
        <convo>_<node>~c3              a character segment of a split line
        <convo>_<node>#df_race_elf     a template-variable variant clip
        <convo>_<node>~c3#df_race_elf  both
    Matching only the first two is how variant clips used to be left behind in the old bucket:
    Dragonfall has 580 of them, and build_voicepack.py reads them as f"{seg_key}#{vid}".
    ~gN is deliberately excluded — narration belongs to the narrator, not to either character.
    """
    bases = {f"{convo}_{n}" for n in nodes}
    out = []
    for k in bucket:
        stem = k.split("#", 1)[0]
        base, _, seg = stem.partition("~")
        if base in bases and (not seg or seg.startswith("c")):
            out.append(k)
    return out


def move_takes(takes, audio_root, src, dst, convo, nodes, clear_selected=False, log=print):
    """Carry every take for these nodes from bucket `src` to bucket `dst`. Returns the keys moved.

    `clear_selected` drops the keeper. Use it whenever the words the clip says are no longer the
    words the line is going to say: a take record stores no text and no hash of it, so a stale clip
    is indistinguishable from a good one and build_voicepack.py would ship it.

    "No keeper" is written as `"selected": None`, NEVER by removing the key. The take store's
    convention is that the key is always present — server.py's /api/generate reads arr["selected"]
    directly — and popping it made every subsequent generate on that line raise KeyError, kill the
    request thread and close the socket with no response. From the lab that reads as "generate
    failed: Failed to fetch"; from gen_batch.py as "Remote end closed connection without response".
    208 Dragonfall entries were left in that state for an hour on 2026-08-10.
    """
    if src not in takes:
        return []
    moved = []
    for k in take_keys(takes[src], convo, nodes):
        entry = takes[src].pop(k)
        for tk in entry.get("takes", []):
            old_rel = tk["file"]
            if not old_rel.startswith(src + "/"):
                continue
            new_rel = dst + old_rel[len(src):]
            old_abs = os.path.join(audio_root, *old_rel.split("/"))
            new_abs = os.path.join(audio_root, *new_rel.split("/"))
            if os.path.exists(new_abs) or os.path.exists(old_abs):
                if not os.path.exists(new_abs):
                    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                    shutil.move(old_abs, new_abs)
                if entry.get("selected") == old_rel:
                    entry["selected"] = new_rel
                tk["file"] = new_rel
            else:
                # The audio is gone. Leaving the path under the OLD bucket hands the new owner a
                # record pointing into a character it does not own, which reads as a real take
                # forever; the record is kept (it is history) but re-pointed, and it must not stay
                # selected — build_voicepack.py would look for a file that is not there.
                log(f"    WARN: take audio missing for {k}, kept the record: {old_rel}")
                tk["file"] = new_rel
                if entry.get("selected") == old_rel:
                    entry["selected"] = None
        if clear_selected:
            entry["selected"] = None
        cur = takes.setdefault(dst, {}).get(k)
        if cur is None:
            takes[dst][k] = entry
        else:   # the target already had takes for this line: keep both, target's keeper wins
            have = {t["file"] for t in cur["takes"]}
            cur["takes"].extend(t for t in entry["takes"] if t["file"] not in have)
            cur["selected"] = cur.get("selected") or entry.get("selected")
        moved.append(k)
    if not takes[src]:
        takes.pop(src)
    return moved


def clear_selected(takes, bucket, keys, log=print):
    """Drop the keeper take on these keys, leaving the clips in place to audition.

    For lines that do NOT change owner but whose spoken text does: the old clip says the old words.
    """
    n = 0
    for k in keys:
        entry = (takes.get(bucket) or {}).get(k)
        if entry and entry.get("selected"):
            entry["selected"] = None
            n += 1
    return n


def move_lines(src_char, dst_char, convo, nodes):
    """Move the nodes from one cast entry's line list to the other's. Returns how many moved."""
    keep, moved = [], 0
    for ln in src_char["lines"]:
        if ln.get("c") == convo and ln.get("n") in nodes:
            dst_char["lines"].append(ln)
            moved += 1
        else:
            keep.append(ln)
    src_char["lines"] = keep
    dst_char["lines"].sort(key=lambda l: (str(l.get("c")), l.get("n") or 0))
    return moved


def ensure_character(chars, by_id, cid, name, **fields):
    """Get or create a cast entry. New people get the shape a corrected extract would produce."""
    c = by_id.get(cid)
    if c:
        return c, False
    c = {"id": cid, "name": name, "portrait": fields.get("portrait"),
         "archetype": fields.get("archetype"), "bio": None, "lines": []}
    for k, v in fields.items():
        if k not in ("portrait", "archetype") and v is not None:
            c[k] = v
    chars["characters"].append(c)
    by_id[cid] = c
    return c, True
