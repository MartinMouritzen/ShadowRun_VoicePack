# Bark gates

Some vanilla floating-text barks fire far more often than their author meant. A gate tells the
plugin which conversation a bark is actually supposed to follow, so the stray firings stay silent.

## The problem

The scene-script event **`On Conversation Complete` takes no conversation parameter**. Verified
across all five content packs: every single one of the 45 `Display Text ...` actions sitting under
such a trigger has an event with zero inputs. The event fires when *any* conversation ends on the
map; the trigger's own **conditions** are the only thing narrowing it down.

That is fine when the conditions flip shortly after — most of these triggers are gated on a
variable the following beat changes, or sit on a `*_OFF` trigger that starts disabled. It is not
fine when the conditions stay true for the rest of an act. Then the same bubble is redrawn after
*every* conversation on the map, for hours.

Nobody noticed in vanilla, because a `Display Text over Actor` bubble is anchored to that actor's
position. Once the conversation UI closes the camera is usually on someone else, so the bubble drew
off-screen and expired unread. **The voice pack is what promoted it into something the player
perceives** — our audio is global, not positional. So this is a regression the mod introduces, not
vanilla behaviour worth preserving, and gating it is a fix rather than a liberty.

### The case that prompted this

`berlin_campaign/data/scenes/haven.srt.bytes`, trigger `Act2_HumanisAccepted_PostDietrich`:

```
EVENT  On Conversation Complete            (no parameters)
COND   Haven_hasHeardDietrichStory_Humanis IS true
COND   Global_MissionState_Humanis == 2
THEN   Enable Interactable Object (Dietrich)
THEN   Display Text over Actor (Dietrich, style 0 speech bubble,
       "I'm counting on you, boss.", wait 2.0s, duration 3.0s)
```

Both conditions hold for the whole Humanis mission and nothing ever turns the trigger off, so
Dietrich says his line every time you finish talking to *anyone* in the Haven. The intended firing
is identifiable: `Haven_hasHeardDietrichStory_Humanis` is set by convo `523cc440346238d0260069af`
(the Dietrich Humanis conversation, auto-started on region enter by the sibling trigger
`Act2_HumanisAccepted_DietrichConvo`), so the bark is meant to follow that conversation and no
other.

## How to add one

1. Find the offending bark's key — `bark_<md5(text)[:16]>`, the same key it has in `barks.json`.
2. Find the conversation it should follow. Its id is the `Get Map Item (Conversation)` argument on
   whichever trigger starts it, or the file name under `data/convos/`.
3. Add an entry to `app/data/<game>/bark_gates.json`:

```json
"bark_cb21efd76e602264": {
  "afterConvo": "523cc440346238d0260069af",
  "speaker": "Dietrich",
  "text": "I'm counting on you, boss.",
  "why": "why this trigger over-fires, and how the conversation was identified"
}
```

`afterConvo` also accepts a list, for a bark that legitimately follows any of several
conversations. Fill in `why` properly: the next person needs to be able to check the reasoning
against the scene data without re-deriving it.

4. `tools/build_voicepack.py` emits `voicepack/<game>/voicepack.gates` (TSV,
   `barkKey<TAB>convoId...`). A gate whose bark has no clips is skipped with a note, so a mistyped
   key shows up as "gate not emitted" rather than silently doing nothing.
5. `sync_to_game.sh` and `build_dist.sh` install it beside `voicepack.index`.

The bark keeps its clips in the pack. Gating changes *when* it is spoken, not whether it exists —
so if a gate turns out to be wrong, deleting the entry restores the old behaviour with no
regeneration.

## How the plugin decides

`VoicePack` loads `voicepack.gates` (absent file = no gates, which is what a pack built before this
feature has). `Patch_FloatingText` consults it right after the enable/disable config checks and
before the debounce.

The test is `ConvoGate.Allows`, which accepts **either** the conversation still current
(`Patch_StartConversation.LastConvo`) **or** the one that most recently ended
(`ConvoGate.LastEnded`, captured in `Patch_EndConversation` before `LastConvo` is cleared). Both are
checked on purpose: whether the engine raises the scene's `ConversationComplete` event before or
after `ConversationManager.EndConversation` runs decides which of the two holds the id, and that
ordering is internal to the engine. Accepting either is correct under both orders.

With `LogLines` on, a suppressed bark logs

```
gated FT[DisplayTextOverActor] bark_<key> — wants convo <id>, saw current=<id> lastEnded=<id>
```

which is also how you confirm a new gate matches on the firing you meant to keep.
