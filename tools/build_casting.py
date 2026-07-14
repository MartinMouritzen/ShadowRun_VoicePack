#!/usr/bin/env python3
"""Assign candidate ElevenLabs voices (Magnific catalog ids) to DMS characters -> app/data/casting.json"""
import json, os, re

ROOT = os.path.join(os.path.dirname(__file__), "..")
chars = json.load(open(os.path.join(ROOT, "app/data/characters.json")))
sel = json.load(open(os.path.join(ROOT, "app/data/samples_selection.json")))

V = {  # id: (name, short desc) — from Magnific catalog, English/elevenlabs only
 597:("Charles Haversham","distinguished British baritone, theatrical gravitas"),
 307:("Henry Fletcher","deep textured British, subtle roughness"),
 441:("Noah Reed","deep, resonant, slightly husky"),
 366:("Ethan Parker","hyper-deep US narrator, commanding"),
 545:("Elias Thornwell","seasoned storyteller, gravitas + warmth"),
 319:("Benjamin Walker","rugged intimate baritone, hard-lived"),
 296:("James Smith","deep resonant authority"),
 37:("Logan West","smooth deep American, rugged"),
 27:("Ethan Brooks","American with slight rasp, authentic"),
 440:("Liam Hayes","deep velvety baritone, commanding clarity"),
 536:("Dana Slate","droll sarcasm, deadpan queen"),
 542:("Selene Vex","dark velvet, low, subtly dangerous"),
 159:("Avery Grant","deep sassy, bold with attitude"),
 287:("Sophia Brown","confident bold American"),
 316:("Merry Cooper","femme fatale, allure + menace"),
 359:("Jacob Harrison","deep gritty Southern drawl"),
 538:("Wade Red Dawson","deep gravelly Texan soul"),
 541:("Jack Thornhill","British grit, working-class edge"),
 544:("Jack Riker","gruff, high-intensity"),
 600:("Jack Rawlins","thunderous, cinematic power"),
 361:("Olivia Roberts","sinister eloquent villainess, calculated"),
 528:("Lilith Vexmoor","calm, clever, dangerously composed"),
 290:("Charlotte Harrington","authoritative British female, polished"),
 258:("Sophia Elizabeth","elegant relaxed British, cold-capable"),
 684:("Avery Quinn","androgynous poetic, theatrical depth"),
 516:("Dominic Blaze","smug theatrical, charismatic villain"),
 523:("Viremont LeNoir","aristocratic, sardonic, dark elegance"),
 526:("Eldros the Wise","ancient, mysterious, enchanted charisma"),
 511:("Dorian Malice","measured menace, psychologically complex"),
 598:("Tom Spencer","clear British warmth, trustworthy"),
 447:("Caleb Morgan","deep rich warm confident"),
 446:("Logan Scott","crisp professional broadcast"),
 333:("Matthew Reynolds","smooth sultry, molasses flow"),
 796:("Winston Brown","Jamaican raspy edge, street soul"),
 36:("Blake Hudson","warm engaging grandpa storyteller"),
 390:("James Carter","rugged wise old cowboy"),
 841:("Walter Hansen","resonant Midwestern elder, calm authority"),
 276:("Sipho Dlamini","South African storyteller warmth"),
 534:("Old Pip Quickroot","high-pitched raspy gnome, comedic"),
 40:("Chase Reed","young Australian, natural energy"),
 47:("Tyler Quinn","relaxed young adult, informal"),
 269:("Logan Christopher","youthful baritone, sarcastic energy"),
 507:("Dylan Hayes","warm neutral young male"),
 270:("Henry Arthur","warm deep young British"),
 372:("William Anderson","cheerful playful young American"),
 686:("Terry Dobson","eccentric husky Northerner"),
 859:("Archer Harrison","clear engaging youthful"),
 588:("Chad Waters","laid-back surfer stoke"),
 291:("Emma Johnson","friendly approachable American"),
 334:("Madison Taylor","relaxed soothing, calm and pleasant"),
 347:("Eleanor Hastings","soft gentle British storyteller"),
 445:("Sophie Walker","engaging expressive storyteller"),
 293:("Olivia Smith","expressive young American"),
 310:("Merry Thompson","sophisticated young British"),
 245:("Ava Madison","clean easy young American"),
 29:("Ava Jordan","clear enthusiastic young British"),
 261:("Harper Olivia","velvety charm, playful-wise"),
 364:("Sophia Morgan","reflective velvety calm, somber"),
 629:("Paige Turner","articulate, warm, emotionally nuanced"),
 565:("Martina Bruno","affectionate grandmother warmth"),
 568:("Remedios García","serene elderly, peaceful"),
 525:("Noctavia La Bruja","sardonic aristocratic disdain, theatrical"),
 532:("Nyra Robot Voice","calm precise AI/computer voice"),
 543:("Axel Virex","robotic edge, synthetic sci-fi"),
 339:("Infernal Colossus","dark menacing demon/monster"),
 589:("Skryth the Withered","Gollum-like feral madness"),
 522:("Malgorn the Hollow","ancient monstrous evil gravitas"),
 518:("Dr. Cosmo Fizzlebaum","lively quirky oddball charm"),
 520:("Mortimer Nocturne","brooding Eastern European gothic"),
 460:("Chiara De Santis","sharp, direct, gritty professional"),
 531:("Vera Raze","bright energetic, infectious"),
 163:("Vivian Lane","soothing calm British"),
}

MAINS = {
 "narrator": [597, 307, 366, 545, 441],
 "name_jakearmitage": [319, 37, 27, 440, 296],
 "name_coyote": [536, 542, 159, 287, 316],
 "name_samwatts": [359, 538, 541, 600, 544],
 "name_jessicawatts": [361, 528, 290, 258, 684],
 "name_harlequin": [516, 523, 526, 511, 598],
}
OVERRIDES = {
 "name_baronsamedi": 796, "name_mrskubota": 364, "name_johnnyclean": 333,
 "name_cherrybomb": 261, "name_jamestelestrianiii": 523, "name_aljernon": 518,
 "name_mcklusky": 544, "name_shannonhalfsky": 629, "name_dresden": 447,
 "name_mrdelilah": 516, "name_fatherwillyhansen": 841, "name_fatheromalley": 36,
 "name_drsaracastle": 290, "name_vangraas": 598, "name_mrkluwe": 686,
 "name_tbgruberman": 538, "name_marielouise": 347, "name_paco": 269,
 "name_drholmes": 511, "name_ryker": 543, "name_tickler": 589,
}
FEM_TOUGH=[159,536,287,531,542,316]; FEM_WARM=[291,334,347,445,293,310,245,29,629,163]
FEM_OLD=[364,163]; M_GRUFF=[359,541,544,27,296,37,440,538,600]; M_SMOOTH=[447,446,333,598,516]
M_OLD=[36,390,841,276]; M_YOUNG=[40,47,269,507,270,372,686,859,588]
ROBOT=532; TURRET=543; SPIRIT=[339,589,522]

used = {}
def take(pool, key):
    i = used.get(id(pool), 0)
    used[id(pool)] = i + 1
    return pool[i % len(pool)]

def gender_of(c):
    p = ((c.get("portrait") or "") + " " + (c.get("portraitFile") or "")).lower()
    if "female" in p: return "f"
    if "male" in p: return "m"
    n = c["name"].lower()
    if re.search(r'\b(mrs|ms|lady|girl|woman|sister|madam|mother|witch|she)\b', n): return "f"
    if any(w in n for w in ["jessica","sally","lorraine","marie","sara","cherry","coyote","shannon"]): return "f"
    return "m"

def classify(c):
    n = c["name"].lower(); a = (c.get("archetype") or "").lower()
    p = ((c.get("portrait") or "")).lower()
    if any(w in n for w in ["computer","terminal","database","board","security control","system","store"]): return ROBOT
    if any(w in n for w in ["turret","drone"]): return TURRET
    if any(w in n for w in ["spirit","soul","abomination","ghost","watcher"]) or "spirit" in p: return take(SPIRIT, n)
    g = gender_of(c)
    old = any(w in n for w in ["old","elder","father","doctor","dr.","professor"]) or "old" in p
    young = any(w in n for w in ["kid","boy","punk","junkie","tweaker","new ","bunraku"])
    tough = any(w in a for w in ["guard","gang","thug","mercenary","hunt","destroy","seek"]) or \
            any(w in n for w in ["guard","cop","officer","gang","boss","muscle","bouncer","soldier"])
    if g == "f":
        if old: return take(FEM_OLD, n)
        if tough or young: return take(FEM_TOUGH, n)
        return take(FEM_WARM, n)
    if old: return take(M_OLD, n)
    if young: return take(M_YOUNG, n)
    if tough: return take(M_GRUFF, n)
    return take(M_SMOOTH, n) if any(w in n for w in ["mr","clean","dealer","john"]) else take(M_GRUFF, n)

casting = {}
def vrec(vid): return {"voiceId": vid, "voiceName": V[vid][0], "voiceDesc": V[vid][1]}
# mains first, in display order
for cid, vids in MAINS.items():
    if cid == "narrator" or cid in sel:
        casting[cid] = {"main": True, "voices": [vrec(v) for v in vids]}
for cid, s in sel.items():
    if cid in casting: continue
    c = next((x for x in chars["characters"] if x["id"] == cid), None)
    if not c: continue
    vid = OVERRIDES.get(cid) or classify(c)
    casting[cid] = {"main": False, "voices": [vrec(vid)]}

json.dump(casting, open(os.path.join(ROOT, "app/data/casting.json"), "w"), indent=1)
n_main = sum(1 for v in casting.values() if v["main"])
print(f"casting: {len(casting)} characters ({n_main} mains with 5 candidates)")
jobs = 0
for cid, cast in casting.items():
    ns = 3 if cast["main"] else 5
    jobs += len(cast["voices"]) * min(ns, len(sel[cid]["samples"]))
print(f"generation jobs: {jobs}")
