"""Resolve conversation-node speaker records from ``speakers.cvsl.bytes``.

Hong Kong stores an additional speaker UID on conversation node field 15.  The UID refers to an
entry in ``data/misc/speakers.cvsl.bytes`` (top-level repeated field 1; entry display name field 2,
portrait field 3, UID field 10).  This is especially important for actorless nodes in conversations
that deliberately switch among several people.  Crucially, field 15 is only active when node field
14 (``override_speaker`` in ShadowrunDTO) is true.  The editor leaves many stale field-15 values on
nodes whose flag is false, so using the UID without the flag silently changes the wrong speakers.
All field-15 values in the currently shipped Hong Kong packs are dormant in this way.

The registry is conservative: a speaker record is used only when its normalized display name or
portrait identifies exactly one already-indexed scene actor.  Device/document records that have no
corresponding actor therefore continue through the extractor's existing fallback chain.
"""
import glob
import os


def load_speaker_registry(content_packs, packs, fields, decode_string):
    """Return ``speaker_uid -> {name, portrait, note, pack}`` for the requested packs."""
    result = {}
    for pack in packs:
        pattern = os.path.join(content_packs, pack, "data/misc/speakers.cvsl.bytes")
        for path in glob.glob(pattern):
            with open(path, "rb") as handle:
                data = handle.read()
            for field_no, wire_type, entry in fields(data):
                if field_no != 1 or wire_type != 2:
                    continue
                strings = {f: decode_string(v) for f, wt, v in fields(entry) if wt == 2}
                uid = strings.get(10)
                if uid:
                    result[uid] = {
                        "name": strings.get(2),
                        "portrait": strings.get(3),
                        "note": strings.get(1),
                        "pack": pack,
                    }
    return result


def resolve_registry_actor(speaker_uid, registry, actors, normalize):
    """Resolve a field-15 UID to one unambiguous existing actor, else ``None``.

    Name is preferred because two intentionally distinct actors may reuse portrait art.  Portrait
    is the identity bridge for aliases such as ``Young Ork`` -> Gobbet and ``Downstairs Tenant`` ->
    Racter.  Ambiguous matches are deliberately rejected.
    """
    speaker = registry.get(speaker_uid)
    if not speaker:
        return None

    wanted_name = normalize(speaker.get("name"))
    if wanted_name:
        matches = [aid for aid, actor in actors.items()
                   if normalize(actor.get("name")) == wanted_name]
        # Scene files commonly contain several physical instances of the same character.  They
        # all collapse to the same output bucket, so choosing the first exact-name instance is
        # deterministic and does not weaken identity.
        if matches:
            return matches[0]

    wanted_portrait = normalize(speaker.get("portrait"))
    if wanted_portrait:
        matches = [aid for aid, actor in actors.items()
                   if normalize(actor.get("portrait")) == wanted_portrait]
        identities = {normalize(actors[aid].get("name")) for aid in matches}
        if matches and len(identities) == 1:
            return matches[0]
    return None


def resolve_node_actor(src_ref, src_tag, override_speaker, speaker_uid, actors, tag_lookup,
                       registry, normalize):
    """Apply the mechanical speaker priority for a non-GM, non-input conversation node.

    Explicit scene references and tags remain authoritative.  Field 15 fills only the actorless
    gap; unresolved registry records return ``(None, None)`` so the caller can use its established
    conversation-name/owner fallback.
    """
    if src_ref and src_ref in actors:
        return src_ref, "source-ref"
    if src_tag:
        aid = tag_lookup(src_tag)
        if aid:
            return aid, "source-tag"
    if override_speaker:
        aid = resolve_registry_actor(speaker_uid, registry, actors, normalize)
        if aid:
            return aid, "active-speaker-override"
    return None, None
