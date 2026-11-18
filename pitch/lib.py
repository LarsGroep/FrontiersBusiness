import cairo, math, json, sys, subprocess, random
W, H, FPS = 1920, 1080, 30
# ---------- colours ----------
def hx(h, a=1.0):
    h = h.lstrip('#'); return (int(h[0:2], 16)/255, int(h[2:4], 16)/255, int(h[4:6], 16)/255, a)
BG1, BG2 = hx('#FFF3F5'), hx('#FFDDE4')
PINK, PINK2, PINK3 = hx('#FFC9D3'), hx('#F9AEBE'), hx('#FFE7EC')
RED, RED2 = hx('#F27383'), hx('#E65C6E')
DEEP, INK = hx('#8E2F47'), hx('#5C2234')
WHITE = hx('#FFFFFF')
GREY, GREY2 = hx('#D8C9CE'), hx('#B9A6AD')
SKIN = ['#F3CBA9', '#DDA47E', '#B0724F', '#7C4B34', '#E8B896']
HAIR = ['#3A2230', '#6E3B2B', '#1F1519', '#CFC7CC', '#8A4A2E', '#E9E2E4']

# ---------- helpers ----------
def clamp(x, a=0, b=1): return max(a, min(b, x))
def prog(t, a, b): return clamp((t-a)/(b-a)) if b > a else (1.0 if t >= a else 0.0)
def eio(x): return x*x*(3-2*x)
def eout(x): return 1-(1-x)**3
def back(x):
    c1 = 1.70158; c3 = c1+1
    return 1 + c3*(x-1)**3 + c1*(x-1)**2
def lerp(a, b, x): return a+(b-a)*x
def col(ctx, c, a=1.0): ctx.set_source_rgba(c[0], c[1], c[2], c[3]*a)
def mix(c1, c2, x): return tuple(lerp(c1[i], c2[i], x) for i in range(4))

def rrect(ctx, x, y, w, h, r):
    r = min(r, w/2, h/2)
    ctx.new_sub_path()
    ctx.arc(x+w-r, y+r, r, -math.pi/2, 0); ctx.arc(x+w-r, y+h-r, r, 0, math.pi/2)
    ctx.arc(x+r, y+h-r, r, math.pi/2, math.pi); ctx.arc(x+r, y+r, r, math.pi, 1.5*math.pi)
    ctx.close_path()

def shadow(ctx, drawfn, dy=10, a=0.10):
    ctx.save(); ctx.translate(0, dy); drawfn(); col(ctx, DEEP, a); ctx.fill(); ctx.restore()

FACES = {'b': ('Poppins', cairo.FONT_WEIGHT_BOLD), 'm': ('Poppins Medium', cairo.FONT_WEIGHT_NORMAL),
         'r': ('Poppins', cairo.FONT_WEIGHT_NORMAL), 'l': ('Poppins Light', cairo.FONT_WEIGHT_NORMAL)}
def font(ctx, size, w='b'):
    f, wt = FACES[w]; ctx.select_font_face(f, cairo.FONT_SLANT_NORMAL, wt); ctx.set_font_size(size)
def text(ctx, s, x, y, size, c=INK, w='b', align='c', a=1.0, track=0):
    if a <= 0: return 0
    font(ctx, size, w)
    if track:
        widths = [ctx.text_extents(ch).x_advance + track for ch in s]
        tw = sum(widths) - track
    else:
        tw = ctx.text_extents(s).x_advance
    x0 = x - tw/2 if align == 'c' else (x - tw if align == 'r' else x)
    col(ctx, c, a)
    if track:
        cx = x0
        for ch, wd in zip(s, widths):
            ctx.move_to(cx, y); ctx.show_text(ch); cx += wd
    else:
        ctx.move_to(x0, y); ctx.show_text(s)
    return tw
def twidth(ctx, s, size, w='b'):
    font(ctx, size, w); return ctx.text_extents(s).x_advance
def wrap(ctx, s, size, maxw, w='m'):
    font(ctx, size, w); words = s.split(); lines = []; cur = ''
    for wd in words:
        t = (cur+' '+wd).strip()
        if ctx.text_extents(t).x_advance > maxw and cur: lines.append(cur); cur = wd
        else: cur = t
    if cur: lines.append(cur)
    return lines

# ---------- background ----------
random.seed(4)
PARTS = [(random.random()*W, random.random()*H, random.uniform(2, 6), random.uniform(0.2, 1), random.random()*6.28) for _ in range(46)]
BLOBS = [(300, 220, 380, 0.0), (1650, 300, 330, 1.7), (1500, 900, 420, 3.1), (250, 950, 300, 4.4)]
def background(ctx, T):
    g = cairo.LinearGradient(0, 0, W*0.4, H); g.add_color_stop_rgba(0, *BG1); g.add_color_stop_rgba(1, *BG2)
    ctx.set_source(g); ctx.paint()
    for (bx, by, r, ph) in BLOBS:
        x = bx + 40*math.sin(T*0.15+ph); y = by + 30*math.cos(T*0.12+ph)
        rg = cairo.RadialGradient(x, y, 0, x, y, r)
        rg.add_color_stop_rgba(0, 1, 0.78, 0.83, 0.55); rg.add_color_stop_rgba(1, 1, 0.78, 0.83, 0)
        ctx.set_source(rg); ctx.arc(x, y, r, 0, 6.29); ctx.fill()
    for (px, py, r, sp, ph) in PARTS:
        y = (py - T*12*sp) % (H+40) - 20; x = px + 14*math.sin(T*0.5*sp+ph)
        col(ctx, WHITE, 0.55); ctx.arc(x, y, r, 0, 6.29); ctx.fill()

# ---------- characters ----------
def woman(ctx, x, y, s=1.0, v=0, walk=0.0, a=1.0, dress=None, wave=0.0, bob=0.0):
    """x,y = feet centre. ~ 300px tall at s=1."""
    skin = hx(SKIN[v % len(SKIN)]); hair = hx(HAIR[[0,1,2,3,4,5,1][v % 7]])
    dress = dress or [RED, PINK2, RED2, hx('#F48FA0'), hx('#FBB3C0')][v % 5]
    style = v % 5
    ctx.save(); ctx.translate(x, y + bob); ctx.scale(s, s)
    ctx.push_group()
    # shadow
    col(ctx, DEEP, 0.10); ctx.save(); ctx.scale(1, 0.18); ctx.arc(0, 0, 70, 0, 6.29); ctx.restore(); ctx.fill()
    # hair back
    col(ctx, hair)
    if style == 0:   # long
        rrect(ctx, -40, -300, 80, 110, 36); ctx.fill()
    elif style == 1: # bob
        ctx.arc(0, -268, 44, 0, 6.29); ctx.fill(); rrect(ctx, -44, -270, 88, 46, 16); ctx.fill()
    elif style == 2: # bun
        ctx.arc(0, -318, 22, 0, 6.29); ctx.fill(); ctx.arc(0, -268, 40, 0, 6.29); ctx.fill()
    elif style == 3: # short grey
        ctx.arc(0, -270, 41, 0, 6.29); ctx.fill()
    else:            # ponytail
        ctx.arc(0, -268, 40, 0, 6.29); ctx.fill(); rrect(ctx, 26, -290, 26, 90, 13); ctx.fill()
    # legs
    sw = math.sin(walk*2*math.pi)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND); ctx.set_line_width(16)
    for sgn in (-1, 1):
        col(ctx, mix(skin, DEEP, 0.15)); ctx.move_to(sgn*16, -110); ctx.line_to(sgn*16 + sgn*0 + 22*sw*sgn*-1, -6); ctx.stroke()
    # dress
    col(ctx, dress)
    ctx.move_to(-28, -215); ctx.curve_to(-40, -170, -62, -130, -66, -100)
    ctx.curve_to(-30, -88, 30, -88, 66, -100); ctx.curve_to(62, -130, 40, -170, 28, -215)
    ctx.curve_to(10, -225, -10, -225, -28, -215); ctx.fill()
    # arms
    ctx.set_line_width(15); col(ctx, skin)
    ctx.move_to(-30, -205); ctx.line_to(-46 - 8*sw, -130); ctx.stroke()
    if wave > 0:
        ang = -2.3 + 0.35*math.sin(wave*12)
        ctx.move_to(30, -205); ctx.line_to(30+70*math.cos(ang), -205+70*math.sin(ang)); ctx.stroke()
    else:
        ctx.move_to(30, -205); ctx.line_to(46 + 8*sw, -130); ctx.stroke()
    # neck
    ctx.set_line_width(14); ctx.move_to(0, -222); ctx.line_to(0, -240); ctx.stroke()
    # face
    col(ctx, skin); ctx.arc(0, -262, 34, 0, 6.29); ctx.fill()
    # fringe
    col(ctx, hair); ctx.move_to(-36, -262); ctx.curve_to(-36, -305, 36, -310, 37, -268)
    ctx.curve_to(15, -285, -10, -282, -36, -262); ctx.fill()
    # eyes + cheeks
    col(ctx, INK); ctx.arc(-12, -258, 3.6, 0, 6.29); ctx.fill(); ctx.arc(12, -258, 3.6, 0, 6.29); ctx.fill()
    col(ctx, RED, 0.35); ctx.arc(-20, -246, 6, 0, 6.29); ctx.fill(); ctx.arc(20, -246, 6, 0, 6.29); ctx.fill()
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a)
    ctx.restore()

def doctor(ctx, x, y, s=1.0, a=1.0, v=2):
    skin = hx(SKIN[v]); hair = hx('#2A1B22')
    ctx.save(); ctx.translate(x, y); ctx.scale(s, s); ctx.push_group()
    col(ctx, DEEP, 0.10); ctx.save(); ctx.scale(1, 0.18); ctx.arc(0, 0, 70, 0, 6.29); ctx.restore(); ctx.fill()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND); ctx.set_line_width(17); col(ctx, hx('#7C5A66'))
    for sgn in (-1, 1): ctx.move_to(sgn*17, -110); ctx.line_to(sgn*17, -6); ctx.stroke()
    # coat
    col(ctx, WHITE); rrect(ctx, -52, -222, 104, 132, 26); ctx.fill()
    col(ctx, hx('#EBDDE1')); ctx.move_to(0, -222); ctx.line_to(0, -90); ctx.set_line_width(3); ctx.stroke()
    col(ctx, PINK2); ctx.move_to(-14, -222); ctx.line_to(0, -192); ctx.line_to(14, -222); ctx.close_path(); ctx.fill()
    # stethoscope
    ctx.set_line_width(5); col(ctx, RED2); ctx.move_to(-18, -218); ctx.curve_to(-30, -170, 10, -160, 14, -150); ctx.stroke()
    ctx.arc(16, -146, 8, 0, 6.29); ctx.fill()
    # arms
    ctx.set_line_width(17); col(ctx, WHITE); ctx.move_to(-50, -205); ctx.line_to(-60, -130); ctx.stroke()
    ctx.move_to(50, -205); ctx.line_to(60, -130); ctx.stroke()
    col(ctx, skin); ctx.arc(-60, -126, 9, 0, 6.29); ctx.fill(); ctx.arc(60, -126, 9, 0, 6.29); ctx.fill()
    ctx.set_line_width(14); ctx.move_to(0, -222); ctx.line_to(0, -238); ctx.stroke()
    col(ctx, skin); ctx.arc(0, -262, 34, 0, 6.29); ctx.fill()
    col(ctx, hair); ctx.move_to(-35, -262); ctx.curve_to(-38, -308, 38, -308, 35, -262); ctx.curve_to(20, -290, -20, -290, -35, -262); ctx.fill()
    col(ctx, INK); ctx.arc(-12, -258, 3.6, 0, 6.29); ctx.fill(); ctx.arc(12, -258, 3.6, 0, 6.29); ctx.fill()
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a); ctx.restore()

def qmark(ctx, x, y, s, a):
    if a <= 0: return
    ctx.save(); ctx.translate(x, y); ctx.scale(s, s)
    col(ctx, WHITE, a); ctx.arc(0, 0, 30, 0, 6.29); ctx.fill()
    text(ctx, '?', 0, 15, 42, RED2, 'b', a=a); ctx.restore()

# ---------- heart ----------
def heart_path(ctx, cx, cy, s):
    ctx.new_path()
    n = 120
    for i in range(n+1):
        t = i/n*2*math.pi
        x = 16*math.sin(t)**3
        y = 13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
        px, py = cx + x*s, cy - y*s
        if i == 0: ctx.move_to(px, py)
        else: ctx.line_to(px, py)
    ctx.close_path()
def piece_path(ctx, cx, cy, s):
    # puzzle piece in upper-right lobe
    x0, y0, w, h = cx + 2*s, cy - 15*s, 15*s, 12*s
    ctx.new_sub_path(); ctx.rectangle(x0, y0, w, h)
    ctx.new_sub_path(); ctx.arc(x0, y0 + h*0.55, 2.4*s, 0, 6.29)
    ctx.new_sub_path(); ctx.arc(x0 + w*0.5, y0 + h, 2.4*s, 0, 6.29)
def heart(ctx, cx, cy, s, a=1.0, missing=1.0, pdx=0, pdy=0, pa=1.0, color=None, glow=0):
    color = color or RED
    if glow > 0:
        rg = cairo.RadialGradient(cx, cy-4*s, 0, cx, cy-4*s, 26*s)
        rg.add_color_stop_rgba(0, 1, 0.55, 0.62, 0.45*glow); rg.add_color_stop_rgba(1, 1, 0.6, 0.66, 0)
        ctx.set_source(rg); ctx.arc(cx, cy-4*s, 26*s, 0, 6.29); ctx.fill()
    ctx.save(); ctx.push_group()
    # shadow
    heart_path(ctx, cx, cy+0.8*s, s); col(ctx, DEEP, 0.10); ctx.fill()
    if missing > 0:
        ctx.save()
        ctx.rectangle(0, 0, W, H); piece_path(ctx, cx, cy, s)
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD); ctx.clip()
        ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        heart_path(ctx, cx, cy, s); col(ctx, color); ctx.fill()
        heart_path(ctx, cx, cy, s); ctx.clip()
        # highlight
        col(ctx, WHITE, 0.25); ctx.arc(cx - 8*s, cy - 7*s, 3.2*s, 0, 6.29); ctx.fill()
        ctx.restore()
        # dashed outline of hole
        ctx.save(); heart_path(ctx, cx, cy, s); ctx.clip()
        piece_path(ctx, cx, cy, s); ctx.set_dash([8, 8]); ctx.set_line_width(4); col(ctx, RED2, 0.6); ctx.stroke(); ctx.restore()
        # floating piece
        if pa > 0:
            ctx.save(); ctx.translate(pdx, pdy)
            piece_path(ctx, cx, cy, s); ctx.clip()
            heart_path(ctx, cx, cy, s); col(ctx, PINK2, pa); ctx.fill()
            ctx.restore()
    else:
        heart_path(ctx, cx, cy, s); col(ctx, color); ctx.fill()
        heart_path(ctx, cx, cy, s); ctx.save(); ctx.clip()
        col(ctx, WHITE, 0.25); ctx.arc(cx - 8*s, cy - 7*s, 3.2*s, 0, 6.29); ctx.fill(); ctx.restore()
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a); ctx.restore()

# ---------- props ----------
def paper(ctx, x, y, w=110, rot=0.0, a=1.0, tag=None, scale=1.0):
    if a <= 0: return
    h = w*1.3
    ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.scale(scale, scale)
    ctx.push_group()
    rrect(ctx, -w/2, -h/2+8, w, h, 10); col(ctx, DEEP, 0.10); ctx.fill()
    rrect(ctx, -w/2, -h/2, w, h, 10); col(ctx, WHITE); ctx.fill()
    col(ctx, PINK2); rrect(ctx, -w/2+12, -h/2+14, w*0.55, 9, 4.5); ctx.fill()
    for i in range(5):
        col(ctx, GREY, 0.9); rrect(ctx, -w/2+12, -h/2+34+i*15, (w-24)*(0.95 if i % 3 else 0.7), 6, 3); ctx.fill()
    if tag == 'f':
        col(ctx, RED); ctx.arc(w/2-18, h/2-18, 11, 0, 6.29); ctx.fill()
        ctx.set_line_width(3); col(ctx, WHITE); ctx.arc(w/2-18, h/2-20, 5, 0, 6.29); ctx.stroke()
        ctx.move_to(w/2-18, h/2-15); ctx.line_to(w/2-18, h/2-9); ctx.stroke()
    elif tag == 'm':
        col(ctx, GREY2); ctx.arc(w/2-18, h/2-18, 11, 0, 6.29); ctx.fill()
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a); ctx.restore()

def person_icon(ctx, x, y, s, c, a=1.0):
    col(ctx, c, a); ctx.arc(x, y - 14*s, 8*s, 0, 6.29); ctx.fill()
    rrect(ctx, x - 12*s, y - 3*s, 24*s, 22*s, 9*s); ctx.fill()

def card(ctx, x, y, w, h, a=1.0, r=26, c=WHITE):
    if a <= 0: return
    ctx.save(); ctx.push_group()
    rrect(ctx, x, y+10, w, h, r); col(ctx, DEEP, 0.08); ctx.fill()
    rrect(ctx, x, y, w, h, r); col(ctx, c); ctx.fill()
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a); ctx.restore()

def pill(ctx, s, x, y, size=26, fg=WHITE, bg=RED, a=1.0, w='m', pad=22):
    if a <= 0: return
    tw = twidth(ctx, s, size, w); hh = size*1.75
    rrect(ctx, x - tw/2 - pad, y - hh/2, tw + 2*pad, hh, hh/2); col(ctx, bg, a); ctx.fill()
    text(ctx, s, x, y + size*0.36, size, fg, w, a=a)

def logo_mark(ctx, cx, cy, s, a=1.0):
    if a <= 0: return
    ctx.save(); ctx.translate(cx, cy); ctx.scale(s, s); ctx.push_group()
    # arch
    ctx.set_line_width(14); ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    col(ctx, RED); ctx.move_to(-60, 70); ctx.line_to(-60, -10); ctx.arc(0, -10, 60, math.pi, 0); ctx.line_to(60, 70); ctx.stroke()
    col(ctx, PINK2); ctx.move_to(-34, 70); ctx.line_to(-34, -6); ctx.arc(0, -6, 34, math.pi, 0); ctx.line_to(34, 70); ctx.stroke()
    heart(ctx, 0, 30, 1.45, missing=0, color=RED2)
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a); ctx.restore()

def logo(ctx, cx, cy, s=1.0, a=1.0, sub=None, sa=1.0):
    if a <= 0: return
    ctx.save(); ctx.translate(cx, cy); ctx.scale(s, s)
    logo_mark(ctx, 0, -120, 1.0, a)
    text(ctx, 'ANARCHA', -6, 60, 92, DEEP, 'b', a=a, track=10, align='c')
    tw = twidth(ctx, 'ANARCHA', 92) + 60
    pill(ctx, 'AI', tw/2 + 52, 30, 40, WHITE, RED, a, 'b', 18)
    if sub: text(ctx, sub, 0, 130, 34, INK, 'm', a=a*sa)
    ctx.restore()

def clock(ctx, x, y, r, T, a=1.0, speed=1.0):
    if a <= 0: return
    card(ctx, x - r - 6, y - r - 6, 2*r + 12, 2*r + 12, a, r + 6)
    ctx.set_line_width(6); col(ctx, PINK2, a); ctx.arc(x, y, r - 8, 0, 6.29); ctx.stroke()
    for i in range(12):
        ang = i/12*6.283
        col(ctx, GREY2, a); ctx.arc(x + (r-22)*math.cos(ang), y + (r-22)*math.sin(ang), 3, 0, 6.29); ctx.fill()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    m = T*speed*6.283; h = m/12
    col(ctx, INK, a); ctx.set_line_width(7); ctx.move_to(x, y); ctx.line_to(x + (r*0.4)*math.sin(h), y - (r*0.4)*math.cos(h)); ctx.stroke()
    col(ctx, RED2, a); ctx.set_line_width(5); ctx.move_to(x, y); ctx.line_to(x + (r*0.62)*math.sin(m), y - (r*0.62)*math.cos(m)); ctx.stroke()
    col(ctx, RED2, a); ctx.arc(x, y, 7, 0, 6.29); ctx.fill()

def door(ctx, x, y, label, a=1.0, open_=0.0):
    if a <= 0: return
    ctx.save(); ctx.push_group()
    rrect(ctx, x - 95, y - 300, 190, 300, 18); col(ctx, PINK); ctx.fill()
    rrect(ctx, x - 78, y - 284, 156, 284, 12); col(ctx, mix(PINK3, WHITE, 0.3)); ctx.fill()
    col(ctx, RED2); ctx.arc(x + 52, y - 140, 8, 0, 6.29); ctx.fill()
    pill(ctx, label, x, y - 340, 24, WHITE, RED2, 1.0, 'm', 18)
    ctx.pop_group_to_source(); ctx.paint_with_alpha(a); ctx.restore()

def ecg(ctx, x0, x1, y, T, a=1.0, amp=60, c=RED2, lw=6, reveal=1.0):
    if a <= 0: return
    ctx.save(); ctx.set_line_width(lw); ctx.set_line_cap(cairo.LINE_CAP_ROUND); ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    period = 260; n = int((x1-x0)*reveal)
    first = True
    for i in range(0, n, 3):
        x = x0 + i
        ph = ((x - T*240) % period)/period
        if 0.40 < ph < 0.44: dy = -amp*(ph-0.40)/0.04
        elif 0.44 <= ph < 0.50: dy = -amp + 1.6*amp*(ph-0.44)/0.06
        elif 0.50 <= ph < 0.54: dy = 0.6*amp - 0.6*amp*(ph-0.50)/0.04
        elif 0.68 < ph < 0.78: dy = -0.18*amp*math.sin((ph-0.68)/0.10*math.pi)
        else: dy = 0
        if first: ctx.move_to(x, y+dy); first = False
        else: ctx.line_to(x, y+dy)
    col(ctx, c, a); ctx.stroke(); ctx.restore()

def caption(ctx, s, a):
    if a <= 0 or not s: return
    lines = wrap(ctx, s, 34, 1300, 'm')
    lh = 48; h = lh*len(lines) + 30
    wmax = max(twidth(ctx, l, 34, 'm') for l in lines) + 70
    y0 = H - 70 - h
    rrect(ctx, W/2 - wmax/2, y0, wmax, h, 24); col(ctx, INK, 0.72*a); ctx.fill()
    for i, l in enumerate(lines):
        text(ctx, l, W/2, y0 + 15 + lh*(i+0.72), 34, WHITE, 'm', a=a)

# ---------- scenes ----------
