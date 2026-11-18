import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *
import numpy as np

T = '/tmp/claude-0/-home-claude/c2a77f63-d7e3-5739-9783-eb4d61a5a83a/scratchpad/tsne'
co = json.load(open(f'{T}/coords.json'))
themes = {t['id']: t for t in json.load(open(f'{T}/data/clusters.json'))['themes'] if t['level'] == 1}
NAME = {17: 'Mental health', 11: 'Postpartum depression', 19: 'Pregnancy care and birth', 1: 'Breast cancer treatment',
        23: 'Treatments and surgery', 3: 'Heart and blood pressure', 14: 'Caesarean section', 9: 'Pre-eclampsia and placenta',
        25: 'Pregnancy complications', 4: 'High blood pressure in pregnancy', 20: 'Exercise', 21: 'Diet and obesity',
        15: 'Contraception', 30: 'Gestational diabetes', 28: 'HPV and cervical cancer', 27: 'Breast screening',
        8: 'Bone health', 12: 'Menopause', 7: 'Endometriosis', 29: 'Breast cancer detection', 16: 'Breast cancer genetics',
        24: 'PCOS', 6: 'Brain and cognition', 5: 'Infections in pregnancy', 22: 'Cervical screening', 13: 'IVF and fertility',
        26: 'Diabetes in pregnancy', 10: 'Breastfeeding', 2: 'COVID-19', 18: 'Microbiome'}
HEART = [3, 4]
SHOW = [17, 19, 1, 15, 28, 8, 12, 7, 24, 13, 20, 2]          # other labels shown
TINTS = [hx(c) for c in ['#E8AFC0', '#C7B3DD', '#AFCBE3', '#F1C9A0', '#B6D9C2', '#DDB8DB', '#D4BFAE', '#BCC6EA']]

xy = np.array(co['xy']); l1 = [x if x is not None else -1 for x in co['l1']]
lo, hi = xy.min(0), xy.max(0)
MX, MY, MW, MH = 90, 215, 1240, 830
s = min(MW/(hi[0]-lo[0]), MH/(hi[1]-lo[1]))
ox = MX + (MW - s*(hi[0]-lo[0]))/2; oy = MY + (MH - s*(hi[1]-lo[1]))/2
P = [(ox + s*(x - lo[0]), oy + s*(hi[1] - y)) for x, y in xy]
ids = sorted(themes)
color = {tid: TINTS[i % len(TINTS)] for i, tid in enumerate(ids)}
cent = {}
for tid in ids:
    pts = np.array([p for p, l in zip(P, l1) if l == tid])
    if len(pts): cent[tid] = np.median(pts, 0)

# themes as packed bubbles placed near their position on the map
cnt = {tid: sum(1 for l in l1 if l == tid) for tid in ids}
tot = sum(cnt.values())
K = math.sqrt(0.50*MW*MH/(math.pi*tot))
B = {tid: [cent[tid][0], cent[tid][1], K*math.sqrt(cnt[tid])] for tid in ids if tid in cent}
home = {tid: (v[0], v[1]) for tid, v in B.items()}
cx0, cy0 = MX + MW/2, MY + MH/2
for it in range(600):
    for i in B:
        for j in B:
            if i >= j: continue
            dx = B[j][0] - B[i][0]; dy = B[j][1] - B[i][1]; d = math.hypot(dx, dy) or 0.01
            m = B[i][2] + B[j][2] + 6 - d
            if m > 0:
                ux, uy = dx/d, dy/d
                B[i][0] -= ux*m/2; B[i][1] -= uy*m/2; B[j][0] += ux*m/2; B[j][1] += uy*m/2
    for i in B:
        B[i][0] += 0.02*(home[i][0] - B[i][0]) + 0.004*(cx0 - B[i][0])
        B[i][1] += 0.02*(home[i][1] - B[i][1]) + 0.004*(cy0 - B[i][1])
        B[i][0] = min(max(B[i][0], MX + B[i][2]), MX + MW - B[i][2])
        B[i][1] = min(max(B[i][1], MY + B[i][2]), MY + MH - B[i][2])

def draw(stage, out):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); ctx = cairo.Context(surf)
    background(ctx, 3.0)
    for tid, (x, y, R) in B.items():
        heart = tid in HEART
        c = (RED2 if tid == 3 else DEEP) if heart else color[tid]
        if stage == 2 and not heart: c = mix(c, GREY, 0.6)
        fa = 0.22 if (stage == 1 or heart) else 0.12
        col(ctx, c, fa); ctx.arc(x, y, R, 0, 6.29); ctx.fill()
        n = cnt[tid]; da = 0.9 if (stage == 1 or heart) else 0.35
        col(ctx, c, da)
        for k in range(n):
            rr = (R - 3)*math.sqrt((k + 0.5)/n); th = k*2.39996
            ctx.rectangle(x + rr*math.cos(th) - 1.1, y + rr*math.sin(th) - 1.1, 2.2, 2.2)
        ctx.fill()
        if heart and stage == 2:
            ctx.set_line_width(5); col(ctx, c, 1); ctx.arc(x, y, R + 6, 0, 6.29); ctx.stroke()
    for tid, (x, y, R) in B.items():
        heart = tid in HEART
        size = 20 if heart else 16
        lines = wrap(ctx, NAME[tid], size, 2*R*0.82, 'b')
        while len(lines) > 3 and size > 12:
            size -= 1; lines = wrap(ctx, NAME[tid], size, 2*R*0.82, 'b')
        ta = 1.0 if (stage == 1 or heart) else 0.45
        for i, l in enumerate(lines):
            yy = y + size*0.36 + (i - (len(lines) - 1)/2)*(size + 5)
            tw = twidth(ctx, l, size, 'b') + 12
            rrect(ctx, x - tw/2, yy - size*0.95, tw, size*1.35, 6); col(ctx, WHITE, (0.85 if not heart else 1)*ta); ctx.fill()
            text(ctx, l, x, yy, size, (RED2 if tid == 3 else DEEP) if heart else INK, 'b', a=ta)
    # side panel
    bx, by, bw, bh = 1400, 300, 440, 560
    card(ctx, bx, by, bw, bh, 1.0)
    if stage == 1:
        text(ctx, '30', bx + bw/2, by + 150, 120, RED2, 'b')
        for i, l in enumerate(['research themes, found', 'by the computer itself']):
            text(ctx, l, bx + bw/2, by + 215 + i*40, 28, INK, 'm')
        text(ctx, '36,678 studies with a', bx + bw/2, by + 370, 24, GREY2, 'm')
        text(ctx, 'text fingerprint', bx + bw/2, by + 404, 24, GREY2, 'm')
        text(ctx, 'Each dot is one study', bx + bw/2, by + 500, 24, INK, 'b')
    else:
        n3 = sum(1 for l in l1 if l == 3); n4 = sum(1 for l in l1 if l == 4)
        text(ctx, '2 heart themes', bx + bw/2, by + 90, 36, INK, 'b')
        col(ctx, RED2); ctx.arc(bx + 60, by + 190, 16, 0, 6.29); ctx.fill()
        text(ctx, 'Heart and blood pressure', bx + 92, by + 182, 24, INK, 'b', 'l')
        text(ctx, f'{n3:,} studies', bx + 92, by + 218, 24, GREY2, 'm', 'l')
        col(ctx, DEEP); ctx.arc(bx + 60, by + 300, 16, 0, 6.29); ctx.fill()
        text(ctx, 'High blood pressure', bx + 92, by + 292, 24, INK, 'b', 'l')
        text(ctx, 'in pregnancy', bx + 92, by + 326, 24, INK, 'b', 'l')
        text(ctx, f'{n4:,} studies', bx + 92, by + 362, 24, GREY2, 'm', 'l')
        text(ctx, 'The heart in general, and', bx + bw/2, by + 460, 24, INK, 'm')
        text(ctx, 'the heart in pregnancy', bx + bw/2, by + 496, 24, INK, 'm')
    surf.write_to_png(out)

if __name__ == '__main__':
    draw(int(sys.argv[1]), sys.argv[2])
