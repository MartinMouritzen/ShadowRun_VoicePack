"""Find the PEOPLE inside a terminal.

`Computer`, `Admin Terminal`, `Message File` and their kin are surfaces, not characters. Most of
what they display was written by somebody: a Shadowland BBS post, an email from a fixer, a lab
technician's journal. Voiced as one machine voice, the terminal impersonates every one of them.

This module reads a container character's lines and reports, per node, whose words they are. It
never guesses: a node it cannot place comes back as UNKNOWN for a human to resolve in the per-game
hand file, the same way build_line_segments.py surfaces unresolved segments rather than inventing a
verb it does not know.

The unit of work is a CONVERSATION, not a node. A Shadowland post can open on one node and close
two nodes later (Hong Kong 278-279, "Looking for experienced decker..."), and a posted news article
runs six (433-439). A per-node parser cannot see either.
"""
import re

# ---------------------------------------------------------------- BBS posts
# The written form is  >>>>>[body]<<<<<  followed by  "- Handle <timestamp>".  Every part of that
# is unreliable in the shipped data, so each is matched loosely. Observed breakages, all real:
#   HK 138  the closing bracket is missing entirely           (crumpeteer)
#   HK 405  the closing marker is <<<< rather than <<<<<      (The Chromed Accountant)
#   HK 532  the leading dash is missing                       (Tin Helmet)
#   DF 411  the tag is not a timestamp: <Strikes Again!/Ha-Ha-Ha>  (The Smiling Bandit)
#   HK 278  the post spans two nodes
OPEN = re.compile(r'>>>>>[ \t]*\[?')
CLOSE = re.compile(r'\][ \t]*<<<<+|<<<<+')
SIG = re.compile(r'^[ \t]*-?[ \t]*(?P<who>[^<>\n]{1,44}?)[ \t]*<(?P<tag>[^<>\n]*)>[ \t]*$')

# ---------------------------------------------------------------- mail headers
MAIL_STAR = re.compile(r'^>>[ \t]*\*(?P<who>[^*\n]+?)\*[ \t]*$', re.M)
MAIL_FROM = re.compile(r'^>>[ \t]*From:[ \t]*(?P<who>.+?)[ \t]*$', re.M | re.I)
MAIL_BARE = re.compile(r'^>>(?P<who>[A-Z][^\n:<>]{1,40}?)[ \t]*$', re.M)
MAIL_FIELD = re.compile(r'^>>[ \t]*(?:to|subject|from|cc)[ \t]*:', re.M | re.I)

# A sign-off ends a mail: "-Beckenbauer", "Yours,\nSilke", "\\m/\n-ThOrvald", "- Alice".
SIGNOFF = re.compile(r'^[ \t]*[-–][ \t]*(?P<who>[A-Za-z][A-Za-z0-9 .\'_-]{1,34})[.!]?[ \t]*$')
SIGNOFF_LEAD = re.compile(r'^[ \t]*(?:Yours|Sincerely|Regards|Best|Love)[,.]?[ \t]*$', re.I)

# A signed post on an internal board: "- J. Ngai, Senior Researcher". The role is what separates it
# from prose ending in a dash, so it is required, and it must read like a title rather than a
# sentence. The Namazu lab boards in Hong Kong are written entirely this way.
SIGNED_ROLE = re.compile(r"^[ \t]*[-–][ \t]*(?P<who>[A-Z][A-Za-z0-9.'’ -]{1,30}?)[ \t]*,"
                         r"[ \t]*(?P<role>[A-Z][A-Za-z0-9/&' -]{2,44})[ \t]*$")

# ---------------------------------------------------------------- transcripts
# Two or more "SPEAKER:" prefixes inside one node: the job-negotiation logs, where GUEST and
# P_AMSEL trade lines inside a single screen of text.
TRANSCRIPT = re.compile(r'^(?P<who>[A-Z][A-Z0-9_]{1,20}):[ \t]', re.M)

# ---------------------------------------------------------------- machine text
# Screen furniture the terminal really does say itself. Deliberately a list of SHAPES rather than
# "whatever is left over": a node matching none of these is UNKNOWN, not machine. Getting this
# backwards would silently leave a person's words in the robot voice, which is the bug being fixed.
MACHINE_LINE = re.compile(
    r'^[ \t]*(?:>+|\*{3,}|_{3,}|#+)'
    r"|^[ \t]*[A-Z][A-Z0-9 ()%/&'.,-]{3,}:[ \t]*[-¥\d*]"
    r'|^[ \t]*(?:WARNING|ERROR|NOTICE|ALERT|CURRENT FUNDS|REQUIRED FUNDS|PAYMENT|DEDUCTIONS'
    r'|REMAINING|WINNING BID|ESCROW|FUNDS SENT|AUTOMATED|link_Str|spoofing|group_info)\b')
MACHINE_WHOLE = re.compile(
    r'^[ \t]*(?:No more posts in this thread\.'
    r'|File deleted\.'
    r'|Transfer complete\.'
    r'|Answer stored\.'
    r'|Safe Unlocked!'
    r'|You have no unread messages\.'
    r'|The file has been corrupted\.'
    r'|Run accepted\. Client notification sent\.)[ \t]*$', re.I)

GM = re.compile(r'\{\{GM\}\}[\s\S]*?(?:\{\{/GM\}\}|$)')

BBS = 'bbs'
MAIL = 'mail'
TRANSCRIPT_KIND = 'transcript'
MACHINE = 'machine'
UNKNOWN = 'unknown'


def _sig_head(text):
    """(handle, rest) when `text` begins with a signature line, else (None, text).

    Leading blank lines are skipped: the signature sits under the post, separated by a blank line
    in most nodes and by a line holding a single space in the Hong Kong data.
    """
    lines = text.split('\n')
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        m = SIG.match(lines[i])
        if m:
            who = m.group('who').strip().strip('-').strip()
            if who:
                return who, '\n'.join(lines[i + 1:])
    return None, text


def mail_header(text):
    """The sender named in a mail header at the very top of a node, else None."""
    for rx in (MAIL_STAR, MAIL_FROM):
        m = rx.search(text)
        if m and not text[:m.start()].strip():
            return m.group('who').strip()
    m = MAIL_BARE.search(text)
    if m and not text[:m.start()].strip() and MAIL_FIELD.search(text):
        return m.group('who').strip()
    return None


def signoff(text):
    """The name a node signs off with, else None. Used to confirm a carried-forward attribution."""
    lines = [l for l in text.rstrip().split('\n') if l.strip()]
    for line in reversed(lines[-3:]):
        m = SIGNOFF.match(line)
        if m:
            return m.group('who').strip()
        if SIGNOFF_LEAD.match(line):
            continue
        if len(lines) >= 2 and SIGNOFF_LEAD.match(lines[-2]) and line is lines[-1]:
            return line.strip().rstrip('.')
        break
    return None


def signed_by(text):
    """The author of a node that ends in a signature but carries no header, else None.

    An internal message board has no ">>From:" line: the post is simply signed at the bottom.
    Checked only after the header and BBS forms have been ruled out, so a Shadowland signature
    ("- Maelstrom <10:55:01/…>") never reaches it.
    """
    lines = [l for l in text.rstrip().split('\n') if l.strip()]
    if not lines:
        return None
    m = SIGNED_ROLE.match(lines[-1])
    if m:
        return m.group('who').strip()
    m = SIGNOFF.match(lines[-1])
    if m and len(lines) > 1:
        who = m.group('who').strip()
        # A one-word closing on a line of its own is a name; a sentence fragment is not.
        if who[:1].isupper() and len(who.split()) <= 3:
            return who
    return None


def is_machine(text):
    """Is every non-empty line of this node screen furniture?"""
    body = GM.sub(' ', text).strip()
    if not body:
        return True
    if MACHINE_WHOLE.match(body):
        return True
    lines = [l for l in body.split('\n') if l.strip()]
    return bool(lines) and all(MACHINE_LINE.match(l) for l in lines)


def transcript_speakers(text):
    """The speaker labels of a two-or-more-party transcript node, else []."""
    who = TRANSCRIPT.findall(text)
    return who if len(set(who)) >= 2 else []


def parse_conversation(nodes):
    """Classify one conversation's nodes.

    `nodes` is [(node_index, text)] for the CONTAINER character only, in node order.
    Returns {node_index: {'kind': ..., 'who': ..., 'span': [node,...], 'note': ...}}.

    `span` is the full set of nodes a multi-node post occupies; every node of the span carries the
    same owner so they all move together.
    """
    out = {}
    pending = None          # {'nodes': [...]} — a post opened and not yet closed
    run_owner = None        # sender of the mail whose body is still running
    prev = None

    for n, text in nodes:
        if pending is not None:
            close = CLOSE.search(text)
            if close is None:
                pending['nodes'].append(n)
                prev = n
                continue
            who, _rest = _sig_head(text[close.end():])
            span = pending['nodes'] + [n]
            for m in span:
                out[m] = {'kind': BBS, 'who': who, 'span': list(span)}
            pending = None
            run_owner = None
            prev = n
            continue

        header = mail_header(text)
        if header:
            # A one-node mail signs off in the same node it opens. Without this the run stays open
            # and swallows whatever follows: Beckenbauer's "Here is your payment, as promised.
            # -Beckenbauer" was adopting the payment ledger two nodes later.
            run_owner = None if signoff(text) else header
            out[n] = {'kind': MAIL, 'who': header, 'span': [n]}
            prev = n
            continue

        posts, pos = [], 0
        while True:
            o = OPEN.search(text, pos)
            if not o:
                break
            close = CLOSE.search(text, o.end())
            if close is None:
                pending = {'nodes': [n]}
                break
            who, rest = _sig_head(text[close.end():])
            posts.append(who)
            pos = len(text) - len(rest)

        if pending is not None:
            prev = n
            run_owner = None
            continue
        if posts:
            named = [p for p in posts if p]
            if not named:
                # A closed span with no signature is a banner or an article header:
                # ">>>>>[ WELCOME TO SHADOWLAND ]<<<<<", ">>>>>[from: HK NEWSWIRE...]<<<<<".
                out[n] = {'kind': MACHINE, 'who': None, 'span': [n], 'note': 'banner'}
            elif len(set(posts)) == 1:
                out[n] = {'kind': BBS, 'who': posts[0], 'span': [n]}
            else:
                out[n] = {'kind': BBS, 'who': None, 'span': [n], 'multi': posts}
            run_owner = None
            prev = n
            continue

        speakers = transcript_speakers(text)
        if speakers:
            out[n] = {'kind': TRANSCRIPT_KIND, 'who': None, 'span': [n], 'multi': speakers}
            run_owner = None
            prev = n
            continue

        if is_machine(text):
            out[n] = {'kind': MACHINE, 'who': None, 'span': [n]}
            run_owner = None
            prev = n
            continue

        # Unmarked prose. It continues the mail above it only when it is the very next node of the
        # conversation: the writers author a mail as a contiguous run, and anything else in between
        # (a player reply node, a GM beat) means a new screen. Everything else is UNKNOWN and goes
        # to the hand file — this is where the video messages and the lab journals land, and they
        # need a human to say whose they are.
        if run_owner and prev is not None and n == prev + 1:
            out[n] = {'kind': MAIL, 'who': run_owner, 'span': [n], 'note': 'continuation'}
            if signoff(text):
                run_owner = None       # the letter closed; the next node is a new screen
        else:
            # No header and no open run, but the post signs itself at the bottom: an internal
            # message board writes every post that way ("- J. Ngai, Senior Researcher"). Checked
            # AFTER the continuation branch, or a letter's own closing line would be read as the
            # start of a new message by someone with the same name.
            author = signed_by(text)
            if author:
                out[n] = {'kind': MAIL, 'who': author, 'span': [n], 'note': 'signed'}
            else:
                out[n] = {'kind': UNKNOWN, 'who': None, 'span': [n]}
            run_owner = None
        prev = n

    if pending is not None:
        for m in pending['nodes']:
            out[m] = {'kind': UNKNOWN, 'who': None, 'span': [m], 'note': 'unclosed post'}

    # A signature sits at the BOTTOM of a post, so a long one attributes the nodes ABOVE it too:
    # Dr. Cheung's four-node status report is unsigned until its last node. Walk back over
    # contiguous unplaced nodes and stop at anything that already has an owner or is machine.
    order = [n for n, _ in nodes]
    index = {n: i for i, n in enumerate(order)}
    for n in order:
        e = out.get(n)
        if not e or e.get('note') != 'signed':
            continue
        i = index[n] - 1
        while i >= 0:
            prev_n = order[i]
            back = out.get(prev_n)
            if not back or back['kind'] != UNKNOWN or prev_n != order[i]:
                break
            if prev_n + 1 != order[i + 1]:
                break                      # a gap in the conversation is a different screen
            out[prev_n] = {'kind': MAIL, 'who': e['who'], 'span': [prev_n],
                           'note': 'signed (carried back)'}
            i -= 1
    return out


# A single short token holding punctuation and nothing sentence-like: "\m/", "---", ":)", "<3".
# Thorvald signs off with metal horns, which the TTS reads as "backslash m slash".
_ART = re.compile(r'^[ \t]*(?=\S{1,8}[ \t]*$)(?=\S*[^\w\s])\S+[ \t]*$')


def strip_signoff(text):
    """Drop a letter's closing block: "Yours,\\nSilke", "-Beckenbauer", the "\\m/" Thorvald types.

    Same reasoning as the BBS signature: the name is on screen, and the letter is already being
    read in that person's own voice. Left in, the TTS says "backslash m slash, minus ThOrvald".

    Only the tail is touched, and only lines that cannot be prose: a closing word ("Yours,"), a
    dash-and-name, punctuation art, or a short bare name DIRECTLY under a closing word. A last line
    that ends in sentence punctuation is content and is never removed.
    """
    lines = text.rstrip().split('\n')
    while lines:
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            break
        last = lines[-1]
        if SIGNOFF.match(last) or SIGNOFF_LEAD.match(last) or _ART.match(last):
            lines.pop()
            continue
        prev = next((l for l in reversed(lines[:-1]) if l.strip()), '')
        bare = last.strip()
        if (SIGNOFF_LEAD.match(prev) and len(bare) <= 34 and len(bare.split()) <= 3
                and not bare[-1:] in '.!?:'):
            lines.pop()
            continue
        break
    return '\n'.join(lines)


def spoken_body(text, kind):
    """The words a person actually says, with the screen furniture taken off.

    Markers, the mail header block and the trailing "- Handle <10:55:01/…>" signature all come off:
    the handle is on screen, and once the poster has their own voice, reading it aloud is noise
    (Martin, 2026-08-10). {{GM}} spans are left alone — the segmenter owns those.
    """
    t = text
    if kind == MAIL:
        for rx in (MAIL_STAR, MAIL_FROM):
            m = rx.search(t)
            if m and not t[:m.start()].strip():
                t = t[m.end():]
                break
        else:
            m = MAIL_BARE.search(t)
            if m and not t[:m.start()].strip() and MAIL_FIELD.search(t):
                t = t[m.end():]
        t = '\n'.join(l for l in t.split('\n') if not MAIL_FIELD.match(l))
    # signature lines, wherever they sit
    t = '\n'.join(l for l in t.split('\n') if not SIG.match(l))
    t = OPEN.sub(' ', t)
    t = CLOSE.sub(' ', t)
    t = re.sub(r'^[ \t]*>+[ \t]*', '', t, flags=re.M)
    # Routing preamble left behind once the >> comes off: ">>//-preface:null_field". It is the
    # envelope, not the message, and reads as "slash slash dash preface colon null underscore field".
    t = '\n'.join(l for l in t.split('\n') if not re.match(r'^[ \t]*//', l))
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = strip_signoff(t)
    return re.sub(r'\n{3,}', '\n\n', t).strip()
