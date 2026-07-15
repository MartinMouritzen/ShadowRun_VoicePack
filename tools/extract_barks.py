#!/usr/bin/env python3
"""Extract combat barks ('Display Text over Actor' scene actions) for DMS, attribute each to its
speaker (actor -> character sheet -> name/gender), flag non-verbal grunts. Writes app/data/barks.json.
Standalone (does NOT import/run extract_dms). Keyed bark_<md5(text)> to match the plugin hook."""
import glob, json, os, re, hashlib
SR="/mnt/c/Program Files (x86)/Steam/steamapps/common/Shadowrun Returns/Shadowrun_Data/StreamingAssets/ContentPacks"
DMS=SR+"/dead_man_switch"
OUT=os.path.join(os.path.dirname(__file__),"..","app","data")
def rv(b,i):
    r=0;s=0
    while True:
        x=b[i];i+=1;r|=(x&0x7f)<<s
        if not x&0x80:return r,i
        s+=7
def fields(b):
    i=0;n=len(b)
    while i<n:
        try:tag,i=rv(b,i)
        except IndexError:return
        f,wt=tag>>3,tag&7
        if wt==0:
            try:v,i=rv(b,i)
            except IndexError:return
            yield f,wt,v
        elif wt==1:yield f,wt,b[i:i+8];i+=8
        elif wt==2:
            l,i=rv(b,i)
            if i+l>n:return
            yield f,wt,b[i:i+l];i+=l
        elif wt==5:yield f,wt,b[i:i+4];i+=4
        else:return
def sub(msg,*path):
    cur=msg
    for p in path:
        found=None
        for f,wt,v in fields(cur):
            if f==p and wt==2: found=v;break
        if found is None:return None
        cur=found
    return cur
def subs(m,fn): return [v for f,wt,v in fields(m) if f==fn and wt==2]
def s_(b):
    if b is None:return None
    try:return b.decode('utf-8')
    except:return None
def f1(m):
    v=sub(m,1); 
    return s_(v)

# 1. character sheets (all packs)
sheets={}
for pack in glob.glob(SR+"/*/data/chars/*.ch_sht.bytes"):
    data=open(pack,'rb').read(); uid=arch=portrait=name=None
    for f,wt,v in fields(data):
        if f==1 and wt==2:uid=s_(v)
        elif f==2 and wt==2:arch=s_(v)
        elif f==11 and wt==2:portrait=s_(sub(v,1)) or s_(v)
        elif f==13 and wt==2:name=s_(v)
    if uid: sheets[uid]={"archetype":arch,"portrait":portrait,"name":name}

# 2. actors from DMS scenes + maps (PropInstance field 4)
actors={}
for sf in glob.glob(DMS+"/data/scenes/*.srt.bytes")+glob.glob(DMS+"/data/maps/*.srm.bytes"):
    data=open(sf,'rb').read()
    for prop in subs(data,4):
        idref=s_(sub(prop,10,1))
        if not idref:continue
        pname=s_(sub(prop,1)); disp=s_(sub(prop,8))
        ci=sub(prop,100); sheet_id=None; ci_name=None; ci_portrait=None
        if ci is not None:
            for f,wt,v in fields(ci):
                if f==2 and wt==2:sheet_id=s_(v)
                elif f==8 and wt==2:ci_name=s_(v)
                elif f==40 and wt==2:ci_portrait=s_(sub(v,1)) or s_(v)
        sheet=sheets.get(sheet_id or "",{})
        name=ci_name or disp or sheet.get("name") or sheet.get("archetype") or pname
        portrait=ci_portrait or sheet.get("portrait") or ""
        if idref not in actors:
            actors[idref]={"name":name,"sheet_id":sheet_id,"portrait":portrait,
                           "archetype":sheet.get("archetype")}

def gender_of(portrait, name):
    p=(portrait or "")+" "+(name or "")
    if re.search(r'female',p,re.I):return "female"
    if re.search(r'male',p,re.I):return "male"
    return "?"
NONVERBAL=re.compile(r'^[\s\W]*$|(.)\1{2,}|^[uUoOaAeEhHrRgGzZ\s\.\*!,]+$')
def is_nonverbal(t):
    core=re.sub(r'[^a-zA-Z]','',t)
    if len(core)<2:return True
    # elongated grunt (3+ repeated letters and few real words)
    if re.search(r'([a-zA-Z])\1{2,}',t) and len(t.split())<=2:return True
    return False

# 3. barks: Display Text over Actor -> (text, actorId)
barks={}
for sf in glob.glob(DMS+"/data/scenes/*.srt.bytes")+glob.glob(DMS+"/data/maps/*.srm.bytes"):
    data=open(sf,'rb').read(); scene=os.path.basename(sf).split('.')[0]
    for c1 in subs(data,1):
        for c4 in subs(c1,4):
            for act in subs(c4,1):
                if f1(act)!="Display Text over Actor":continue
                # actor id: a nested "Get Map Item (Actor)" carries a 24-hex id string
                actor_id=None; text=None
                allv=[]
                def collect(m,d=0):
                    if d>6:return
                    for f,wt,v in fields(m):
                        if wt==2:
                            try:
                                s=v.decode('utf-8')
                                if re.fullmatch(r'[0-9a-f]{24}',s): allv.append(('id',s))
                            except:pass
                            collect(v,d+1)
                collect(act)
                for f,wt,v in fields(act):pass
                for cont in subs(act,2):
                    for f,wt,v in fields(cont):
                        if f==4 and wt==2:
                            try:t=v.decode('utf-8').strip()
                            except:continue
                            if len(t)>=3 and not re.fullmatch(r'[0-9a-f]{16,32}',t): text=t
                ids=[x[1] for x in allv]
                actor_id=ids[0] if ids else None
                if not text:continue
                key="bark_"+hashlib.md5(text.encode()).hexdigest()[:16]
                a=actors.get(actor_id or "",{})
                e=barks.get(key)
                if e:
                    e["count"]+=1
                else:
                    barks[key]={"text":text,"speaker":a.get("name") or "Unknown",
                                "sheetId":a.get("sheet_id"),"archetype":a.get("archetype"),
                                "gender":gender_of(a.get("portrait"),a.get("name")),
                                "portrait":a.get("portrait"),"nonverbal":is_nonverbal(text),"count":1}
json.dump(barks,open(os.path.join(OUT,"barks.json"),"w"),ensure_ascii=False,indent=1)
from collections import Counter
spk=Counter(b["speaker"] for b in barks.values() if not b["nonverbal"])
print(f"barks: {len(barks)} unique | non-verbal(skipped): {sum(1 for b in barks.values() if b['nonverbal'])} | voiceable: {sum(1 for b in barks.values() if not b['nonverbal'])}")
print(f"distinct speakers: {len(spk)}")
print("top speakers (voiceable bark count):")
for name,n in spk.most_common(25): print(f"   {n:3}  {name}")
