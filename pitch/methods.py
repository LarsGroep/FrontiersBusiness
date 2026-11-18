import sys, os, json, math, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *

D = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')))
PAT = 1          # the patient from the promo (brown bob, pink dress)
GPV = 0          # the GP
SYMS = [('Tired', 'Fatigue'), ('Breathless', 'Dyspnea'), ('Swollen ankles', 'Edema'), ('Jaw ache', 'Jaw Pain')]
GREEN = hx('#3FA66B')


# ---------- shared pieces ----------
NOTEXT = os.environ.get('NOTEXT') == '1'
def tag(ctx, s, a, bg=RED):
    if NOTEXT: return
    pill(ctx, s, W/2, 62, 20, WHITE, bg, a, 'b', 16)

def headline(ctx, s, a, y=140, size=58):
    if NOTEXT: return
    text(ctx, s, W/2, y, size, INK, 'b', a=a)

def fade(t, dur, fi=0.5, fo=0.5):
    return eio(prog(t, 0, fi)) * eio(1 - prog(t, dur - fo, dur))

def week(ctx, s, a, hot=False):
    if a <= 0: return
    tw = twidth(ctx, s, 34, 'b') + 60
    card(ctx, W - 110 - tw, 110, tw, 70, a, 35)
    text(ctx, s, W - 110 - tw/2, 157, 34, RED2 if hot else GREY2, 'b', a=a)

def timeline(ctx, xs, labels, y, done, a, good=True):
    if a <= 0: return
    ctx.set_line_cap(cairo.LINE_CAP_ROUND); ctx.set_line_width(8)
    col(ctx, PINK, a); ctx.move_to(xs[0] - 40, y); ctx.line_to(xs[-1] + 80, y); ctx.stroke()
    col(ctx, RED if good else GREY2, a); ctx.move_to(xs[0] - 40, y); ctx.line_to(lerp(xs[0], xs[-1], done), y); ctx.stroke()
    for x, l in zip(xs, labels):
        on = x <= lerp(xs[0], xs[-1], done) + 1
        col(ctx, WHITE, a); ctx.arc(x, y, 15, 0, 6.29); ctx.fill()
        col(ctx, RED if on else PINK2, a); ctx.arc(x, y, 9, 0, 6.29); ctx.fill()
        text(ctx, l, x, y + 62, 30, INK, 'b', a=a)

def laptop(ctx, x, y, s, a, glow=0.0, logo_a=1.0):
    if a <= 0: return
    ctx.save(); ctx.translate(x, y); ctx.scale(s, s); ctx.push_group()
    rrect(ctx, -130, -170, 260, 165, 16); col(ctx, INK); ctx.fill()
    rrect(ctx, -118, -158, 236, 141, 8); col(ctx, mix(WHITE, PINK3, glow)); ctx.fill()
    if glow > 0:
        rg = cairo.RadialGradient(0, -88, 0, 0, -88, 160)
        rg.add_color_stop_rgba(0, 1, 0.55, 0.62, 0.35*glow); rg.add_color_stop_rgba(1, 1, 0.6, 0.66, 0)
        ctx.set_source(rg); ctx.arc(0, -88, 160, 0, 6.29); ctx.fill()
    tw = text(ctx, 'ANARCHA', -24, -82, 26, DEEP, 'b', a=logo_a, track=3)
    pill(ctx, 'AI', -24 + tw/2 + 26, -91, 16, WHITE, RED, logo_a, 'b', 9)
    rrect(ctx, -160, -8, 320, 18, 8); col(ctx, GREY2); ctx.fill()
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a); ctx.restore()

def ai_circle(ctx, x, y, r, a, T=0.0, pulse=0.0):
    if a <= 0: return
    for k in range(3):
        ph = (T*0.6 + k/3) % 1.0
        col(ctx, RED, a*pulse*(1 - ph)*0.35); ctx.arc(x, y, r*(1 + ph*0.9), 0, 6.29); ctx.fill()
    col(ctx, WHITE, a); ctx.arc(x, y, r + 10, 0, 6.29); ctx.fill()
    col(ctx, RED, a); ctx.arc(x, y, r, 0, 6.29); ctx.fill()
    text(ctx, 'AI', x, y + r*0.32, r*0.85, WHITE, 'b', a=a)

def counter(ctx, n, label, x, y, a, size=96, c=RED2):
    if a <= 0: return
    text(ctx, f'{int(round(n)):,}', x, y, size, c, 'b', a=a)
    text(ctx, label, x, y + size*0.55, 30, INK, 'm', a=a)

def bubble_pills(ctx, x, y, a_list, size=26, fly=None):
    """Symptom pills stacked above a point; fly[k] = (tx, ty, p) moves pill k to a target."""
    for k, (lab, _) in enumerate(SYMS):
        a = a_list[k]
        if a <= 0: continue
        px, py = x, y - k*58
        if fly and fly[k]:
            tx, ty, p = fly[k]; e = eio(p); px, py = lerp(px, tx, e), lerp(py, ty, e) - 120*math.sin(math.pi*e)
            a *= 1 - prog(p, 0.85, 1.0)
        pill(ctx, lab, px, py, size, WHITE, RED2, a, 'b', 20)

def walker(t, keys):
    """keys = [(time, x)], returns x and walking phase."""
    for (t0, x0), (t1, x1) in zip(keys, keys[1:]):
        if t <= t1:
            p = eio(prog(t, t0, t1)); moving = x1 != x0 and t0 < t < t1
            return lerp(x0, x1, p), ((t - t0)*1.6 if moving else 0.0)
    return keys[-1][1], 0.0


# ---------- 1. she comes back (15 s) ----------
TL = [330, 860, 1390]
def clip1(ctx, t, dur, T):
    A = fade(t, dur, 0.6, 0.01)
    z = eio(prog(t, 11.6, 14.6))                       # zoom into the laptop
    ctx.save()
    lx, ly = 1010, 700
    sc = 1 + 9*z
    ctx.translate(lx, ly - 90); ctx.scale(sc, sc); ctx.translate(-lx, -(ly - 90))
    a0 = A*(1 - prog(t, 11.6, 12.4))
    tag(ctx, 'WITH ANARCHA AI', a0)
    headline(ctx, 'Same patient. Same GP.', a0)
    week(ctx, 'Week 0' if t < 6.5 else 'Week 1', a0, hot=True)
    floor = 800
    x, ph = walker(t, [(0, TL[0]), (5.2, TL[0]), (7.6, 720), (99, 720)])
    timeline(ctx, TL, ['Week 0', 'GP visit', ''], floor + 10, prog(t, 5.2, 7.6)*0.5, a0)
    doctor(ctx, 1220, floor, 1.0, a=A*eout(prog(t, 0.6, 1.4)), v=GPV)
    woman(ctx, x, floor, 1.0, v=PAT, walk=ph, a=A*eout(prog(t, 0.2, 0.9)))
    laptop(ctx, lx, ly - 30, 0.8, A*eout(prog(t, 7.6, 8.3)), glow=prog(t, 9.0, 11.0), logo_a=eout(prog(t, 8.0, 8.6)))
    pa = 1 - prog(t, 8.2, 8.8)
    bubble_pills(ctx, x, 455, [A*pa*eout(prog(t, 1.8 + k*0.5, 2.3 + k*0.5)) for k in range(4)])
    ca = a0*eout(prog(t, 8.6, 9.1))
    if ca > 0:
        cx0, cy0, cw, chh = 700, 235, 640, 215
        card(ctx, cx0, cy0, cw, chh, ca)
        text(ctx, 'GP types in Anarcha', cx0 + 30, cy0 + 44, 22, RED2, 'b', 'l', a=ca)
        full = ['Woman, 57: tired, breathless,', 'swollen ankles, jaw ache']
        n = int(sum(len(l) for l in full) * prog(t, 9.0, 10.6)); shown = []
        for l in full:
            shown.append(l[:max(0, n)]); n -= len(l)
        for i, l in enumerate(shown):
            if l: text(ctx, l, cx0 + 30, cy0 + 92 + i*38, 26, INK, 'm', 'l', a=ca)
        if prog(t, 9.0, 10.6) < 1 and int(t*3) % 2 == 0:
            k = 0 if shown[1] == '' else 1
            col(ctx, RED, ca); ctx.rectangle(cx0 + 34 + twidth(ctx, shown[k], 26, 'm'), cy0 + 70 + k*38, 3, 28); ctx.fill()
        ea = ca*eout(prog(t, 10.8, 11.3))
        if ea > 0:
            rrect(ctx, cx0 + 30, cy0 + 160, 290, 40, 20); col(ctx, PINK3, ea); ctx.fill()
            sig = D['ecg']; ctx.set_line_width(2.5); col(ctx, RED2, ea)
            for i in range(0, 800, 4):
                (ctx.move_to if i == 0 else ctx.line_to)(cx0 + 48 + i*80/800, cy0 + 180 - sig[i]*14)
            ctx.stroke()
            text(ctx, 'ECG attached', cx0 + 142, cy0 + 188, 20, DEEP, 'b', 'l', a=ea)
    ctx.restore()
    # end of the zoom: the screen fills the frame
    if z > 0.85:
        col(ctx, BG1, prog(z, 0.85, 1.0)); ctx.paint()


# ---------- 2. the database (25 s) ----------
MAPBOX = (420, 210, 1080, 800)       # x, y, w, h for the big map
AREA_ORDER = ['Pregnancy', 'Cancer', 'Mental health', 'Nutrition and metabolism', 'Heart and blood vessels']
AREA_COL = {'Pregnancy': PINK2, 'Cancer': hx('#C98AA0'), 'Mental health': hx('#D9A0B0'), 'Nutrition and metabolism': hx('#E8B7C3'),
            'Heart and blood vessels': RED2}
def gate(ctx, x, label, a, glow):
    if a <= 0: return
    rrect(ctx, x - 18, 330, 36, 380, 18); col(ctx, mix(PINK, RED, glow), a); ctx.fill()
    pill(ctx, label, x, 290, 24, WHITE, RED2, a, 'b', 16)

def clip2(ctx, t, dur, T):
    A = fade(t, dur, 0.6, 0.6)
    s1 = A*(1 - prog(t, 7.0, 7.8))
    tag(ctx, 'STEP 1 · THE DATA', A)
    headline(ctx, 'Studies in which only women took part', A)
    # stream of papers through two gates
    if s1 > 0:
        pill(ctx, 'Europe PMC', 230, 520, 26, WHITE, GREY2, s1, 'b', 20)
        gate(ctx, 760, 'Female filter', s1, prog(t, 1.0, 2.0))
        gate(ctx, 1160, 'Checked: only women', s1, prog(t, 1.6, 2.6))
        import random as _r
        rnd = _r.Random(3)
        for k in range(46):
            t0 = k*0.13; p = (t - 0.6 - t0)/2.6
            if p <= 0 or p > 1: continue
            fate = rnd.random()                    # 0..0.3 dropped at gate 1, 0.3..0.42 at gate 2
            y0 = 420 + rnd.random()*200
            x = lerp(330, 1500, p)
            drop = 0.0; tg = 'f'
            if fate < 0.3 and x > 760: drop = (x - 760)/300; tg = 'm'
            elif 0.3 <= fate < 0.42 and x > 1160: drop = (x - 1160)/300; tg = 'm'
            if fate < 0.3 and x < 760: tg = None
            if 0.3 <= fate < 0.42 and x < 1160: tg = None
            xx = x if drop == 0 else (760 if fate < 0.3 else 1160) + 60*drop
            yy = y0 + 420*drop*drop
            paper(ctx, xx, yy, 64, rot=0.15*math.sin(k), a=s1*(1 - clamp(drop)), tag=tg)
        n = 50748*eio(prog(t, 1.2, 6.6))
        counter(ctx, n, 'women-only studies', 1660, 560, s1, 84)
    # the map forms
    mx, my, mw, mh = MAPBOX
    g = eio(prog(t, 8.2, 13.0)); ap = prog(t, 7.6, 8.6)*A
    if ap > 0:
        import random as _r
        rnd = _r.Random(5)
        hl = None
        k_on = [eout(prog(t, 14.0 + i*1.3, 14.6 + i*1.3)) for i in range(len(AREA_ORDER))]
        for (px, py), lab in zip(D['all']['xy'], D['all']['lab']):
            sx, sy = rnd.random(), rnd.random()
            x = mx + lerp(sx, px, g)*mw; y = my + lerp(sy, 1 - py, g)*mh
            cc = GREY; aa = 0.55
            if lab in AREA_ORDER:
                i = AREA_ORDER.index(lab); on = k_on[i]
                if lab != 'Heart and blood vessels': on *= 1 - 0.6*prog(t, 21.0, 22.0)
                if on > 0: cc = mix(GREY, AREA_COL[lab], on); aa = 0.55 + 0.4*on
            col(ctx, cc, ap*aa); ctx.rectangle(x - 1.6, y - 1.6, 3.2, 3.2); ctx.fill()
        # labels at area centres
        for i, lab in enumerate(AREA_ORDER):
            a = A*k_on[i]*(1 - (0.7*prog(t, 21.0, 22.0) if lab != 'Heart and blood vessels' else 0))
            if a <= 0: continue
            pts = [p for p, l in zip(D['all']['xy'], D['all']['lab']) if l == lab]
            cx = sorted(p[0] for p in pts)[len(pts)//2]; cy = sorted(p[1] for p in pts)[len(pts)//2]
            x = mx + cx*mw; y = my + (1 - cy)*mh
            bg = RED2 if lab == 'Heart and blood vessels' else WHITE
            fg = WHITE if lab == 'Heart and blood vessels' else INK
            pill(ctx, lab, x, y, 24, fg, bg, a, 'b', 16)
        text(ctx, 'Similar studies sit close together', W/2, 1050, 32, INK, 'm', a=A*eout(prog(t, 12.0, 12.8)))
        counter(ctx, 50748, 'women-only studies', 1700, 290, A*eout(prog(t, 8.6, 9.4)), 56)


# ---------- 3. symptom filter (20 s) ----------
HB = (640, 230, 760, 780)
def clip3(ctx, t, dur, T):
    A = fade(t, dur, 0.6, 0.6)
    tag(ctx, 'STEP 2 · SYMPTOM FILTER', A)
    headline(ctx, 'Her words find the studies', A)
    floor = 900
    woman(ctx, 300, floor, 1.0, v=PAT, a=A*eout(prog(t, 0.2, 0.8)))
    mx, my, mw, mh = HB
    hx_ = D['heart']['xy']; symf = D['heart']['sym']
    lit = set()
    starts = [5.0 + k*1.6 for k in range(4)]
    for k, (_, key) in enumerate(SYMS):
        if t > starts[k] + 1.0: lit |= set(D['heart'][key])
    ap = A*eout(prog(t, 0.6, 1.6)); sa = prog(t, 2.6, 3.6); dim = prog(t, 11.8, 12.8)
    for i, (px, py) in enumerate(hx_):
        x = mx + px*mw; y = my + (1 - py)*mh
        if i in lit:
            col(ctx, RED, A); ctx.arc(x, y, 4.2, 0, 6.29); ctx.fill(); continue
        cc = mix(GREY, PINK2, sa) if symf[i] else GREY
        col(ctx, cc, ap*(0.6 - 0.4*dim)); ctx.rectangle(x - 1.8, y - 1.8, 3.6, 3.6); ctx.fill()
    # pills fly from her into the map
    fly = [(mx + mw/2, my + mh/2, prog(t, starts[k], starts[k] + 1.0)) for k in range(4)]
    bubble_pills(ctx, 300, 520, [A*eout(prog(t, 0.8 + k*0.3, 1.2 + k*0.3)) for k in range(4)], fly=fly)
    # numbers on the left
    a1 = A*eout(prog(t, 0.8, 1.6))*(1 - prog(t, 2.6, 3.2))
    counter(ctx, 5484, 'heart studies', 1660, 520, a1, 72)
    a2 = A*eout(prog(t, 3.0, 3.8))*(1 - prog(t, 4.6, 5.2))
    counter(ctx, 855, 'describe symptoms', 1660, 520, a2, 72)
    a3 = A*eout(prog(t, 5.4, 6.0))
    counter(ctx, len(lit), 'match her symptoms', 1660, 520, a3, 72, RED2)
    text(ctx, '"No chest pain" does not count', 1660, 700, 26, INK, 'm', a=A*eout(prog(t, 13.0, 13.8)))


# ---------- 4. ECG AI (20 s) ----------
def clip4(ctx, t, dur, T):
    A = fade(t, dur, 0.6, 0.6)
    tag(ctx, 'STEP 3 · ECG AI', A)
    headline(ctx, 'A second AI reads her heart signal', A)
    # monitor card
    cx0, cy0, cw, ch = 160, 230, 1000, 360
    card(ctx, cx0, cy0, cw, ch, A*eout(prog(t, 0.3, 1.0)))
    ga = A*eout(prog(t, 0.3, 1.0))
    if ga > 0:
        ctx.set_line_width(1); col(ctx, PINK, ga)
        for gx in range(cx0 + 40, cx0 + cw - 30, 40): ctx.move_to(gx, cy0 + 60); ctx.line_to(gx, cy0 + ch - 30)
        for gy in range(cy0 + 60, cy0 + ch - 20, 40): ctx.move_to(cx0 + 40, gy); ctx.line_to(cx0 + cw - 40, gy)
        ctx.stroke()
        text(ctx, 'Her ECG · 10 seconds', cx0 + 40, cy0 + 44, 26, INK, 'b', 'l', a=ga)
    sig = D['ecg']; n = len(sig); rev = prog(t, 1.0, 6.0)
    if rev > 0:
        ctx.set_line_width(4); ctx.set_line_join(cairo.LINE_JOIN_ROUND); col(ctx, RED2, A)
        m = int(n*rev); x0, x1, ym, amp = cx0 + 40, cx0 + cw - 40, cy0 + 210, 110
        for i in range(0, m, 2):
            x = lerp(x0, x1, i/n); y = ym - sig[i]*amp
            (ctx.move_to if i == 0 else ctx.line_to)(x, y)
        ctx.stroke()
        if rev < 1:
            col(ctx, RED, A); ctx.arc(lerp(x0, x1, m/n), ym - sig[max(0, m - 1)]*amp, 8, 0, 6.29); ctx.fill()
    # scan + AI
    sc = prog(t, 6.4, 8.4)
    if 0 < sc < 1:
        x = lerp(cx0 + 40, cx0 + cw - 40, sc)
        col(ctx, RED, 0.25*A); ctx.rectangle(x - 30, cy0 + 60, 60, ch - 90); ctx.fill()
    ai_circle(ctx, 1420, 410, 80, A*eout(prog(t, 6.0, 6.8)), T, pulse=prog(t, 6.4, 8.4)*(1 - prog(t, 8.4, 9.0)))
    text(ctx, 'Trained on 80,000 ECGs', 1420, 560, 30, INK, 'b', a=A*eout(prog(t, 6.6, 7.2)))
    text(ctx, 'Tells female from male: 93% (AUROC)', 1420, 604, 26, INK, 'm', a=A*eout(prog(t, 7.0, 7.6)))
    # slider
    sa = A*eout(prog(t, 8.8, 9.5))
    if sa > 0:
        x0, x1, y = 200, 1120, 730
        g = cairo.LinearGradient(x0, 0, x1, 0); g.add_color_stop_rgba(0, *RED[:3], sa); g.add_color_stop_rgba(1, *GREY2[:3], sa)
        rrect(ctx, x0, y - 12, x1 - x0, 24, 12); ctx.set_source(g); ctx.fill()
        text(ctx, 'Looks female', x0, y + 62, 28, RED2, 'b', 'l', a=sa)
        text(ctx, 'Looks male', x1, y + 62, 28, GREY2, 'b', 'r', a=sa)
        pos = lerp(0.5, 0.85, eio(prog(t, 9.6, 11.8)))
        mxp = lerp(x0, x1, pos)
        col(ctx, WHITE, sa); ctx.arc(mxp, y, 26, 0, 6.29); ctx.fill(); col(ctx, INK, sa); ctx.arc(mxp, y, 16, 0, 6.29); ctx.fill()
        pill(ctx, 'Her ECG: 15% female', mxp, y - 70, 26, WHITE, INK, sa*eout(prog(t, 11.6, 12.2)), 'b', 18)
    # risk card with the real survival curves
    ra = A*eout(prog(t, 12.8, 13.6))
    if ra > 0:
        bx, by, bw, bh = 1290, 660, 520, 330
        card(ctx, bx, by, bw, bh, ra)
        text(ctx, 'Women with a normal ECG, 4 years', bx + 30, by + 46, 22, INK, 'b', 'l', a=ra)
        px0, px1, py0, py1 = bx + 40, bx + bw - 40, by + 80, by + bh - 50
        tt = prog(t, 13.4, 16.0)
        for q, cc, lab in (('0', PINK2, 'Most female-looking ECG'), ('3', DEEP, 'Most male-looking ECG')):
            pts = D['km'][q]; ctx.set_line_width(5); col(ctx, cc, ra); first = True
            for tm, s in pts:
                if tm > 4.5*tt: break
                x = lerp(px0, px1, tm/4.5); y = lerp(py0, py1, (1 - s)/0.03)
                (ctx.move_to if first else ctx.line_to)(x, y); first = False
            if not first: ctx.stroke()
        text(ctx, 'Most female-looking: 1.1% died', bx + 30, by + bh - 52 + 0, 22, PINK2, 'b', 'l', a=ra*eout(prog(t, 16.0, 16.6)))
        text(ctx, 'Most male-looking: 2.5% died', bx + 30, by + bh - 20, 22, DEEP, 'b', 'l', a=ra*eout(prog(t, 16.4, 17.0)))
    text(ctx, 'A group risk, not her diagnosis', 700, 1010, 28, INK, 'm', a=A*eout(prog(t, 17.2, 17.8)))


# ---------- 5. decision tree (20 s) ----------
def node_box(ctx, s, x, y, a, on=0.0, size=28, wide=None):
    if a <= 0: return
    tw = wide or twidth(ctx, s, size, 'b') + 60
    rrect(ctx, x - tw/2, y - 34, tw, 68, 20); col(ctx, mix(WHITE, RED, on), a); ctx.fill()
    ctx.set_line_width(4); col(ctx, RED2, a); rrect(ctx, x - tw/2, y - 34, tw, 68, 20); ctx.stroke()
    text(ctx, s, x, y + 10, size, mix(INK, WHITE, on), 'b', a=a)

def clip5(ctx, t, dur, T):
    A = fade(t, dur, 0.6, 0.6)
    tag(ctx, 'STEP 4 · DECISION TREE', A)
    headline(ctx, 'Yes or no, step by step', A)
    path = [('Pregnant?', False, 'Pregnancy problems'), ('Chest pain?', False, 'Coronary heart disease'),
            ('Pelvic pain?', False, 'Other blood vessel conditions'), ('Short of breath?', True, 'High blood pressure')]
    xs = [200, 590, 980, 1370]; y = 420
    for k, (q, ans, other) in enumerate(path):
        ga = A*eout(prog(t, 0.6 + k*0.5, 1.2 + k*0.5))
        on = eout(prog(t, 4.0 + k*2.0, 4.6 + k*2.0))
        # side branch (the answer she did not give) going down
        bx = xs[k] + (0 if k == 0 else 0)
        ctx.set_line_width(5); col(ctx, PINK2, ga*(1 - 0.5*on))
        ctx.move_to(bx, y + 34); ctx.line_to(bx, y + 200); ctx.stroke()
        text(ctx, 'no' if ans else 'yes', bx + 16, y + 120, 24, GREY2, 'm', 'l', a=ga*(1 - 0.5*on))
        pill(ctx, other, bx, y + 236, 22, INK, WHITE, ga*(1 - 0.55*on), 'm', 16)
        # main branch to the next node
        if k < len(path) - 1:
            ctx.set_line_width(6); col(ctx, mix(PINK2, RED, on), ga)
            ctx.move_to(xs[k] + 140, y); ctx.line_to(xs[k + 1] - 140, y); ctx.stroke()
            text(ctx, 'yes' if ans else 'no', (xs[k] + xs[k + 1])/2, y - 18, 26, RED2 if on else GREY2, 'b', a=ga)
        node_box(ctx, q, xs[k], y, ga, on, size=26, wide=280)
        if on > 0:
            pill(ctx, 'YES' if ans else 'NO', xs[k], y - 80, 22, WHITE, RED if ans else GREY2, A*on, 'b', 14)
    # the end point
    ea = A*eout(prog(t, 12.0, 12.8))
    if ea > 0:
        ctx.set_line_width(6); col(ctx, RED, ea); ctx.move_to(xs[-1] + 140, y); ctx.line_to(1580, y); ctx.stroke()
        card(ctx, 1560, y - 110, 300, 220, ea, 26, PINK3)
        text(ctx, 'Heart failure', 1710, y - 30, 38, DEEP, 'b', a=ea)
        text(ctx, 'studies', 1710, y + 14, 30, INK, 'm', a=ea)
        text(ctx, 'best fit for her', 1710, y + 66, 24, RED2, 'b', a=ea)
    # basis
    ba = A*eout(prog(t, 14.0, 14.8))
    text(ctx, 'Learned from 855 studies that describe women\'s symptoms', W/2, 860, 32, INK, 'b', a=ba)
    text(ctx, 'Right group in its top three: 71% (16% by chance)', W/2, 910, 28, INK, 'm', a=A*eout(prog(t, 15.0, 15.8)))
    text(ctx, 'The GP sees exactly why', W/2, 990, 30, RED2, 'b', a=A*eout(prog(t, 16.4, 17.2)))


# ---------- 6. the reasoning agent (20 s) ----------
def mini_map(ctx, x, y, a):
    import random as _r
    rnd = _r.Random(2)
    for _ in range(70):
        px, py = x + rnd.gauss(0, 30), y + rnd.gauss(0, 18)
        col(ctx, RED if rnd.random() < 0.35 else GREY, a); ctx.arc(px, py, 3, 0, 6.29); ctx.fill()

def mini_ecg(ctx, x, y, a):
    sig = D['ecg']; ctx.set_line_width(3); col(ctx, RED2, a)
    for i in range(0, 900, 4):
        (ctx.move_to if i == 0 else ctx.line_to)(x - 70 + i*140/900, y - sig[i]*26)
    ctx.stroke()

def mini_tree(ctx, x, y, a):
    ctx.set_line_width(4); col(ctx, RED2, a)
    ctx.move_to(x - 60, y); ctx.line_to(x - 10, y - 24); ctx.line_to(x + 50, y - 24)
    ctx.move_to(x - 10, y - 24); ctx.line_to(x + 50, y + 10); ctx.move_to(x - 60, y); ctx.line_to(x - 10, y + 28); ctx.stroke()
    for px, py in ((x - 60, y), (x - 10, y - 24), (x + 50, y - 24), (x + 50, y + 10), (x - 10, y + 28)):
        col(ctx, RED, a); ctx.arc(px, py, 7, 0, 6.29); ctx.fill()

def clip6(ctx, t, dur, T):
    A = fade(t, dur, 0.6, 0.8)
    s1 = A*(1 - prog(t, 13.0, 13.8))
    tag(ctx, 'STEP 5 · REASONING AGENT', s1)
    headline(ctx, 'Everything comes together, with sources', s1)
    srcs = [('280 women-only studies', mini_map), ('ECG: male-looking pattern', mini_ecg), ('Tree: heart failure studies', mini_tree)]
    ax, ay = 900, 560
    for k, (lab, fn) in enumerate(srcs):
        a = s1*eout(prog(t, 0.6 + k*0.5, 1.2 + k*0.5))
        y = 330 + k*230
        card(ctx, 90, y - 80, 530, 160, a)
        fn(ctx, 210, y, a)
        text(ctx, lab, 300, y + 10, 23, INK, 'b', 'l', a=a)
        # flowing dots to the agent
        fa = s1*prog(t, 2.6, 3.2)
        if fa > 0:
            ctx.set_line_width(3); col(ctx, PINK2, fa); ctx.move_to(625, y); ctx.curve_to(720, y, 760, ay, ax - 100, ay); ctx.stroke()
            for j in range(4):
                u = ((T*0.5 + j/4 + k*0.13) % 1.0)
                bx = (1-u)**3*625 + 3*(1-u)**2*u*720 + 3*(1-u)*u*u*760 + u**3*(ax - 100)
                by_ = (1-u)**3*y + 3*(1-u)**2*u*y + 3*(1-u)*u*u*ay + u**3*ay
                col(ctx, RED, fa); ctx.arc(bx, by_, 6, 0, 6.29); ctx.fill()
    ai_circle(ctx, ax, ay, 90, s1*eout(prog(t, 2.2, 2.8)), T, pulse=prog(t, 3.0, 3.6))
    # the answer card, as in the promo
    ca = s1*eout(prog(t, 5.0, 5.8))
    if ca > 0:
        bx, by, bw, bh = 1100, 250, 700, 640
        card(ctx, bx, by, bw, bh, ca)
        tw = text(ctx, 'ANARCHA', bx + 40, by + 56, 24, DEEP, 'b', 'l', a=ca, track=3)
        pill(ctx, 'AI', bx + 40 + tw + 24, by + 48, 14, WHITE, RED, ca, 'b', 8)
        q = ['Woman, 57: tired, breathless,', 'swollen ankles, jaw ache. ECG attached.']
        rrect(ctx, bx + 150, by + 100, 510, 110, 22); col(ctx, RED, ca); ctx.fill()
        for i, l in enumerate(q): text(ctx, l, bx + 174, by + 145 + i*36, 22, WHITE, 'm', 'l', a=ca)
        aa = s1*eout(prog(t, 6.6, 7.4))
        lines = ['Women-only studies link these symptoms', 'to heart failure.', 'Her ECG pattern is linked to', 'higher risk in women.']
        rrect(ctx, bx + 40, by + 250, 520, 250, 22); col(ctx, PINK3, aa); ctx.fill()
        for i, l in enumerate(lines): text(ctx, l, bx + 66, by + 300 + i*38 + (16 if i >= 2 else 0), 24, INK, 'm', 'l', a=aa)
        for j, s in enumerate(['[1]', '[2]', '[3]']):
            pill(ctx, s, bx + 90 + j*76, by + 470, 20, WHITE, RED2, s1*eout(prog(t, 7.6 + j*0.25, 8.0 + j*0.25)), 'b', 12)
        text(ctx, 'women-only studies', bx + 330, by + 477, 20, RED2, 'm', 'l', a=s1*eout(prog(t, 8.4, 8.9)))
        text(ctx, 'The doctor decides.', bx + bw/2, by + bh - 50, 30, RED2, 'b', a=s1*eout(prog(t, 9.4, 10.0)))
    # back to the timeline: referral
    e = A*eout(prog(t, 13.8, 14.6))
    if e > 0:
        tag(ctx, 'WITH ANARCHA AI', e)
        headline(ctx, 'Referred straight away, not sent home', e)
        floor = 800
        x, ph = walker(t, [(0, 720), (15.0, 720), (17.2, 1250), (99, 1250)])
        timeline(ctx, [330, 720, 1250, 1640], ['Week 0', 'GP visit', 'Referral', ''], floor + 10, lerp(0.29, 0.6, eio(prog(t, 15.0, 17.2))), e)
        woman(ctx, x, floor, 1.0, v=PAT, walk=ph, a=e)
        doctor(ctx, 1400, floor, 1.0, a=e*eout(prog(t, 16.4, 17.0)), v=3)
        pill(ctx, 'Cardiologist', 1400, floor - 360, 24, WHITE, RED2, e*eout(prog(t, 16.6, 17.2)), 'b', 16)
        ck = e*eout(prog(t, 17.4, 18.0))
        if ck > 0:
            col(ctx, GREEN, ck); ctx.arc(x, floor - 360, 30, 0, 6.29); ctx.fill()
            ctx.set_line_width(7); ctx.set_line_cap(cairo.LINE_CAP_ROUND); ctx.set_line_join(cairo.LINE_JOIN_ROUND); col(ctx, WHITE, ck)
            ctx.move_to(x - 13, floor - 360); ctx.line_to(x - 3, floor - 349); ctx.line_to(x + 14, floor - 372); ctx.stroke()


CLIPS = [(clip1, 15.0), (clip2, 25.0), (clip3, 20.0), (clip4, 20.0), (clip5, 20.0), (clip6, 20.0)]

def frame(i, t):
    f, d = CLIPS[i]; T = sum(c[1] for c in CLIPS[:i]) + t
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); ctx = cairo.Context(surf)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)
    background(ctx, T)
    f(ctx, t, d, T)
    return surf

if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'still':
        frame(int(sys.argv[2]), float(sys.argv[3])).write_to_png(sys.argv[4])
    elif mode == 'clip':
        i, out = int(sys.argv[2]), sys.argv[3]
        n = int(round(CLIPS[i][1]*FPS))
        p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                              '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out],
                             stdin=subprocess.PIPE)
        for k in range(n):
            p.stdin.write(bytes(frame(i, k/FPS).get_data()))
        p.stdin.close(); sys.exit(p.wait())
