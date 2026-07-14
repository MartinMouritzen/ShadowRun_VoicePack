#!/usr/bin/env python3
"""Build app/data/char_notes.json: per-character bio, voice direction, and 3 suggested
ElevenLabs voices (picked from the cached catalog, ids validated by construction)."""
import json, os, re

ROOT = os.path.join(os.path.dirname(__file__), "..")
# Suggestion pills use ONLY Magnific voices (unlimited, no metered quota) — no ElevenLabs.
cat = json.load(open(os.path.join(ROOT, "app/data/magnific_voices.json")))["voices"]
chars = json.load(open(os.path.join(ROOT, "app/data/characters.json")))
sel = json.load(open(os.path.join(ROOT, "app/data/samples_selection.json")))
by_id = {c["id"]: c for c in chars["characters"]}

# id: (bio, direction, search keywords, gender, prefer_age)
N = {
"narrator": ("The unseen game master. Reads every scene description, every consequence, every beat of atmosphere - the most heard voice in the game by far.",
    "Noir gravitas without monotony: a storyteller who can go from dry wit to dread. Distinct from every cast voice.",
    ["narrator","gravelly","deep","storyteller","noir","documentary"], None, "middle_aged"),
"name_jessicawatts": ("Sam's estranged sister and the public face of the Universal Brotherhood - polished, magnetic, and rotten underneath.",
    "Warm, cultured messiah with a cold fanatic core; should sound trustworthy until you listen closely.",
    ["elegant","calm","villain","sophisticated","cold","cult"], "female", "middle_aged"),
"name_coyote": ("Street kid Sam pulled out of the gutter; tends bar and runs shadows to keep the grief at bay.",
    "Young, rough-edged, guarded; sarcasm as armor over real hurt.",
    ["raspy","young","tough","street","sarcastic","attitude"], "female", "young"),
"name_baronsamedi": ("Ghoul crime lord running Seattle's organ-legging trade from the shadows, dressed in loa theatrics.",
    "Caribbean-flavored, theatrical menace: playful cadence, predator underneath.",
    ["jamaican","caribbean","raspy","deep","menacing","accent"], "male", None),
"name_mrskubota": ("Iron-willed matriarch of the Seamstresses Union - keeps her girls safe and her secrets safer.",
    "Older, dignified, unshockable; velvet manners over steel.",
    ["elderly","refined","calm","wise","authoritative"], "female", "old"),
"name_dresden": ("Dwarf coroner at the city morgue; has seen every way a body can stop working and jokes about most of them.",
    "Dry gallows humor, precise diction, unbothered by anything.",
    ["dry","deadpan","mature","precise","gruff"], "male", "middle_aged"),
"name_johnnyclean": ("Legendary decker avatar who haunts the Matrix - all signal, no meat.",
    "Slick late-night-radio cool with a digital sheen; never hurried.",
    ["smooth","radio","cool","late night","charismatic"], "male", None),
"name_harlequin": ("An immortal elf wearing motley and mockery; older than nations and hiding it behind punchlines.",
    "Theatrical trickster: quicksilver comedy that can drop into ancient, chilling weight mid-sentence.",
    ["theatrical","villain","charismatic","dramatic","wit","sardonic"], "male", None),
"name_cherrybomb": ("Elf performer holding court at the club - all glitter, gossip and sharpened nails.",
    "Flirty, playful, dangerous when crossed.",
    ["playful","sultry","flirty","energetic","velvety"], "female", "young"),
"name_jamestelestrianiii": ("Patriarch of Telestrian Industries, one of the most powerful elves in Seattle.",
    "Aristocratic boardroom authority; every word measured, entitled, final.",
    ["aristocratic","refined","authoritative","british","corporate"], "male", "middle_aged"),
"name_mrkluwe": ("Loudmouth troll with opinions on everything and the muscle to back most of them.",
    "Big, brash, fast-talking; fun but genuinely imposing.",
    ["loud","energetic","deep","brash","intense"], "male", None),
"name_mcklusky": ("Ork boss working the docks - equal parts foreman, fixer and brawler.",
    "Gravel and bluster; a voice that has shouted over machinery for decades.",
    ["gruff","gravelly","deep","rough","working"], "male", "middle_aged"),
"name_jakearmitage": ("The courier from the SNES legend himself - a data-run gone wrong made him a street icon.",
    "Laconic street-samurai cool: low, dry, economical. Every word costs him something.",
    ["deep","cool","laconic","rugged","baritone"], "male", "middle_aged"),
"name_drsaracastle": ("Sharp forensic doctor who helps unravel what really happened to Sam.",
    "Competent, warm-professional, quietly wry.",
    ["professional","warm","clear","intelligent"], "female", "middle_aged"),
"name_tweaker": ("Chip-fried informant vibrating between paranoia and salesmanship.",
    "Twitchy, fast, pitch shifting; sounds like he's already three sentences ahead.",
    ["nervous","quirky","fast","eccentric","manic"], "male", "young"),
"name_aljernon": ("Eccentric elf talismonger - part shopkeeper, part oracle, entirely odd.",
    "Whimsical and sly, with genuine arcane depth beneath the patter.",
    ["quirky","whimsical","eccentric","theatrical","charming"], "male", None),
"name_fatherwillyhansen": ("The Universal Brotherhood's beaming public preacher.",
    "Televangelist warmth turned up to eleven; sincerity that feels one notch too smooth.",
    ["preacher","warm","charismatic","booming","persuasive"], "male", "middle_aged"),
"name_paco": ("Street kid and gang lookout who knows every alley in the Barrens.",
    "Young, eager, streetwise; bravado covering nerves.",
    ["young","energetic","street","casual"], "male", "young"),
"name_vangraas": ("Doctor keeping a free clinic alive in a neighborhood that keeps trying to die.",
    "Weary compassion; educated, gentle, permanently tired.",
    ["gentle","tired","mature","kind","calm"], "male", "middle_aged"),
"name_officeraguirre": ("Lone Star beat cop - by the book, but the book still has a conscience.",
    "Steady, procedural, decent; clipped cop cadence.",
    ["authoritative","clear","serious","cop"], "male", "middle_aged"),
"name_drholmes": ("Elf body-shop surgeon with silk manners and flexible ethics.",
    "Silky, reassuring, faintly predatory bedside manner.",
    ["smooth","calm","sinister","refined"], "male", "middle_aged"),
"name_shannonhalfsky": ("Salish shaman investigating the same darkness you are, from the spirit side.",
    "Earnest and grounded with spiritual steel; calm conviction, not mysticism-fog.",
    ["grounded","warm","serious","spiritual","clear"], "female", None),
"name_mrdelilah": ("Impeccably dressed host of the Union's front-of-house - discretion for sale.",
    "Suave underworld concierge; purrs, never raises his voice.",
    ["suave","smooth","velvety","host","charming"], "male", None),
"name_tbgruberman": ("Ork wheeler-dealer; if it fell off a truck, he knows the truck.",
    "Gruff trader bark with a salesman's grin in it.",
    ["gruff","gravelly","salesman","rough"], "male", "middle_aged"),
"name_samwatts": ("The dead man of Dead Man Switch - your old friend, speaking from recordings and memory.",
    "Tired gravel with a good heart; a man who knew he was running out of road.",
    ["gravelly","tired","warm","deep","weathered"], "male", "middle_aged"),
"name_marielouise": ("Telestrian's daughter - poised on the surface, something fragile and wrong beneath.",
    "Refined, brittle porcelain; polite phrases stretched over dread.",
    ["soft","fragile","elegant","haunting"], "female", "young"),
"name_marielouisetelestrian": ("Same person as Marie-Louise - use the same voice for both entries.",
    "Match the Marie-Louise casting exactly.",
    ["soft","fragile","elegant","haunting"], "female", "young"),
"name_mrjohnson": ("The anonymous corporate fixer every runner knows by this name.",
    "Neutral professional menace; friendly words, no warmth.",
    ["neutral","professional","corporate","calm","cold"], "male", "middle_aged"),
"name_hansbrackhaus": ("Urbane emissary with a German edge and resources that should worry you. (Those who know, know.)",
    "Precise, faintly accented, quietly amused, bottomlessly powerful.",
    ["german","precise","refined","commanding","accent"], "male", "middle_aged"),
"name_ghostofgrizzledveteran": ("Spectral soldier still holding a post the living abandoned.",
    "Hollow, weathered, echoing; grief under discipline.",
    ["haunting","hollow","old","ghost","weathered"], "male", "old"),
"name_coyoteugly": ("Coyote before her healing - same person, rougher days. Use the same voice as Coyote.",
    "Match the Coyote casting exactly.",
    ["raspy","young","tough","street"], "female", "young"),
"name_frank": ("Pike Place fishmonger with opinions about everything crossing his stall.",
    "Big market-caller voice; friendly bellow.",
    ["loud","friendly","energetic","working"], "male", "middle_aged"),
"name_janitor": ("Brotherhood janitor who has mopped around things he refuses to think about.",
    "Mumbly, nervous, keeps-his-head-down energy.",
    ["nervous","quiet","mumbling","timid"], "male", "old"),
"name_sadoldman": ("A broken man in the Barrens with nothing left but the story of how.",
    "Thin, cracked, heartbreaking.",
    ["old","frail","sad","soft"], "male", "old"),
"name_headthug": ("Gang muscle with just enough brains to be in charge of the other muscle.",
    "Blunt-force confidence; talks with his chin out.",
    ["tough","thug","deep","aggressive"], "male", None),
"name_hansbrackhaus_dup": None,
}

GENERIC = {
 "terminal": ("A machine interface.", "Clean synthetic voice; polite, inhuman.", ["robot","synthetic","ai","precise"], None, None),
 "spirit": ("A being from the other side of the veil.", "Otherworldly: layered, resonant, wrong in a beautiful way.", ["ethereal","dark","monster","haunting","demon"], None, None),
 "guard": ("Rank-and-file security.", "Professional-bored with a hard edge on demand.", ["guard","serious","clipped","tough"], "male", None),
 "cop": ("Law enforcement.", "Procedural, clipped, unimpressed.", ["authoritative","cop","serious"], "male", None),
 "priest": ("Clergy of the old faith.", "Soft liturgical calm.", ["gentle","calm","wise","warm"], "male", "old"),
 "sister": ("A nun of the parish.", "Kind, steady, quietly firm.", ["gentle","warm","calm"], "female", "middle_aged"),
 "civ_m": ("A Seattle citizen just trying to get by.", "Everyday, natural, unpolished.", ["natural","conversational","casual"], "male", None),
 "civ_f": ("A Seattle citizen just trying to get by.", "Everyday, natural, unpolished.", ["natural","conversational","casual"], "female", None),
}
def generic_for(cid, name, portrait):
    n = name.lower(); p = (portrait or "").lower()
    if any(w in n for w in ["terminal","computer","board","database","security control","system"]): return GENERIC["terminal"]
    if any(w in n for w in ["spirit","ghost","soul","tickler"]): return GENERIC["spirit"]
    if "officer" in n or "lone star" in n: return GENERIC["cop"]
    if any(w in n for w in ["guard","muscle","thug","supervisor"]): return GENERIC["guard"]
    if any(w in n for w in ["brother ","father ","acolyte","patrick"]): return GENERIC["priest"]
    if "sister" in n: return GENERIC["sister"]
    fem = "female" in p or any(w in n for w in ["sally","sarah","saada","woman","cook","concerned"])
    g = dict(zip(["bio","direction","kw","gender","age"], GENERIC["civ_f" if fem else "civ_m"]))
    return (g["bio"], g["direction"], g["kw"], g["gender"], g["age"])

def score(v, kws, gender, age):
    if gender and v.get("gender") and v["gender"] != gender: return -1
    hay = f'{v.get("name","")} {v.get("desc","")} {v.get("accent","")} {v.get("use","")} {v.get("age","")}'.lower()
    s = sum(2 for k in kws if k in hay)
    if v.get("gender") == gender: s += 1
    if age and v.get("age") == age: s += 1
    if "english" not in "en": pass
    if v.get("source") == "mine": s += 0.5   # already in account: no slot juggling
    return s

used_count = {}
def suggest(kws, gender, age, n=8):
    # keep gender-appropriate voices (score>=0), rank by keyword fit with a diversity penalty,
    # and fill up to n so each character gets 6-8 quick-select pills.
    scored = [(score(v, kws, gender, age), v) for v in cat]
    scored = [(s, v) for s, v in scored if s >= 0]
    scored.sort(key=lambda sv: -(sv[0] - 0.6 * used_count.get(sv[1]["voice_id"], 0)))
    out = []
    for s, v in scored:
        out.append({"voice_id": v["voice_id"], "name": v["name"],
                    "why": (v.get("desc") or "")[:90]})
        used_count[v["voice_id"]] = used_count.get(v["voice_id"], 0) + 1
        if len(out) == n: break
    return out

notes = {}
for cid in sel:
    ch = by_id.get(cid) or {"name": "Narrator (GM)", "portrait": None}
    if cid in N and N[cid]:
        bio, direction, kws, gender, age = N[cid]
    else:
        bio, direction, kws, gender, age = generic_for(cid, ch["name"], ch.get("portrait"))
    notes[cid] = {"bio": bio, "direction": direction, "gender": gender,
                  "suggestions": suggest(kws, gender, age)}

json.dump(notes, open(os.path.join(ROOT, "app/data/char_notes.json"), "w"), ensure_ascii=False, indent=1)
n_hand = sum(1 for c in notes if c in N and N[c])
print(f"notes: {len(notes)} characters ({n_hand} hand-written), all suggestion ids from catalog")
empty = [c for c, v in notes.items() if not v["suggestions"]]
print("no suggestions for:", empty or "none")
