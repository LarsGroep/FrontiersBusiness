import sys, os, json, math, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *
import numpy as np
from scipy.ndimage import gaussian_filter
from PIL import Image

T = '/tmp/claude-0/-home-claude/c2a77f63-d7e3-5739-9783-eb4d61a5a83a/scratchpad/tsne'
co = json.load(open(f'{T}/coords.json'))
NAME = {17: 'Mental health', 11: 'Postpartum depression', 19: 'Pregnancy care and birth', 1: 'Breast cancer treatment',
        23: 'Treatments and surgery', 3: 'Heart and blood pressure', 14: 'Caesarean section', 9: 'Pre-eclampsia and placenta',
        25: 'Pregnancy complications', 4: 'High blood pressure in pregnancy', 20: 'Exercise', 21: 'Diet and obesity',
        15: 'Contraception', 30: 'Gestational diabetes', 28: 'HPV and cervical cancer', 27: 'Breast screening',
        8: 'Bone health', 12: 'Menopause', 7: 'Endometriosis', 29: 'Breast cancer detection', 16: 'Breast cancer genetics',
        24: 'PCOS', 6: 'Brain and cognition', 5: 'Infections in pregnancy', 22: 'Cervical screening', 13: 'IVF and fertility',
        26: 'Diabetes in pregnancy', 10: 'Breastfeeding', 2: 'COVID-19', 18: 'Microbiome'}
GROUPS = [('Heart', '#E0475F', [3]), ('Heart in pregnancy', '#8E2F47', [4]),
          ('Pregnancy and birth', '#F08DAE', [19, 14, 9, 25, 30, 26, 10, 5]),
          ('Cancer', '#9C7BD1', [1, 27, 29, 16, 28, 22]), ('Mental health and brain', '#5E9BD6', [17, 11, 6]),
          ('Fertility and contraception', '#EFA25B', [7, 24, 13, 15]), ('Menopause and bones', '#3FAE9C', [12, 8]),
          ('Lifestyle', '#86B94F', [20, 21]), ('Other', '#B3A4AA', [23, 18, 2])]
G_OF = {tid: gi for gi, (_, _, ts) in enumerate(GROUPS) for tid in ts}
LABEL = [3, 4, 19, 1, 17, 15, 12, 8, 20, 28, 13, 2, 24]
HEART = {3, 4}

xy = np.array(co['xy']); l1 = np.array([x if x is not None else -1 for x in co['l1']])
lo, hi = xy.min(0), xy.max(0)
MX, MY, MW, MH = 90, 215, 1240, 830
s = min(MW/(hi[0]-lo[0]), MH/(hi[1]-lo[1]))
ox = MX + (MW - s*(hi[0]-lo[0]))/2; oy = MY + (MH - s*(hi[1]-lo[1]))/2
PX = ox + s*(xy[:, 0] - lo[0]); PY = oy + s*(hi[1] - xy[:, 1])

def halos(stage):
    """Soft coloured regions: per-theme density, blurred, thresholded."""
    img = np.zeros((H, W, 4), np.float32)
    f = 4; gw, gh = W//f, H//f
    for tid in NAME:
        m = l1 == tid
        if m.sum() < 50: continue
        hgrid, _, _ = np.histogram2d(PY[m]/f, PX[m]/f, bins=[gh, gw], range=[[0, gh], [0, gw]])
        d = gaussian_filter(hgrid, 5.0); d /= d.max()
        a = np.clip((d - 0.18)/0.25, 0, 1)
        heart = tid in HEART
        if stage == 2 and not heart: a *= 0.25
        a *= 0.55 if heart else 0.35
        a = np.kron(a, np.ones((f, f)))[:H, :W]
        c = np.array(hx(GROUPS[G_OF[tid]][1])[:3], np.float32)
        if stage == 2 and not heart: c = c*0.4 + np.array(GREY[:3])*0.6
        # "over" compositing in premultiplied space
        img[..., :3] = img[..., :3]*(1 - a[..., None]) + c*a[..., None]
        img[..., 3] = img[..., 3]*(1 - a) + a
    rgba = np.zeros((H, W, 4), np.uint8)
    al = img[..., 3:4]
    rgb = np.where(al > 0, img[..., :3]/np.maximum(al, 1e-6), 0)
    rgba[..., :3] = (rgb*255).clip(0, 255); rgba[..., 3] = (al[..., 0]*255).clip(0, 255)
    # cairo wants premultiplied BGRA
    pm = rgba.astype(np.float32); pm[..., :3] *= pm[..., 3:4]/255
    bgra = pm[..., [2, 1, 0, 3]].astype(np.uint8)
    return cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32, W, H, W*4)

def draw(stage, out):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); ctx = cairo.Context(surf)
    background(ctx, 3.0)
    ctx.set_source_surface(halos(stage), 0, 0); ctx.paint()
    order = np.argsort([1 if t in HEART else 0 for t in l1], kind='stable')
    for i in order:
        tid = int(l1[i]); g = G_OF.get(tid, len(GROUPS) - 1); c = hx(GROUPS[g][1]); heart = tid in HEART
        a = 0.85 if heart else 0.6
        if stage == 2 and not heart: c = mix(c, GREY, 0.7); a = 0.3
        col(ctx, c, a); ctx.arc(PX[i], PY[i], 2.6 if heart else 2.0, 0, 6.29); ctx.fill()
    for tid in LABEL:
        m = l1 == tid
        hgrid, ye, xe = np.histogram2d(PY[m], PX[m], bins=[60, 100], range=[[MY, MY + MH], [MX, MX + MW]])
        d = gaussian_filter(hgrid, 2.0); yi, xi = np.unravel_index(d.argmax(), d.shape)
        x, y = (xe[xi] + xe[xi + 1])/2, (ye[yi] + ye[yi + 1])/2
        heart = tid in HEART; c = hx(GROUPS[G_OF[tid]][1])
        if heart:
            pill(ctx, NAME[tid], x, y, 22, WHITE, c, 1.0, 'b', 14)
        elif stage == 1:
            pill(ctx, NAME[tid], x, y, 17, INK, WHITE, 0.92, 'b', 11)
        else:
            text(ctx, NAME[tid], x, y + 6, 16, GREY2, 'm', a=0.8)
    bx, by, bw, bh = 1400, 240, 440, 680
    card(ctx, bx, by, bw, bh, 1.0)
    if stage == 1:
        text(ctx, '30 themes, 9 groups', bx + bw/2, by + 66, 30, INK, 'b')
        for k, (name, hexc, ts) in enumerate(GROUPS):
            yy = by + 130 + k*54
            col(ctx, hx(hexc)); ctx.arc(bx + 50, yy - 8, 13, 0, 6.29); ctx.fill()
            text(ctx, name, bx + 80, yy, 23, INK, 'm', 'l')
        text(ctx, 'Each dot is one study', bx + bw/2, by + bh - 34, 22, GREY2, 'b')
    else:
        n3 = int((l1 == 3).sum()); n4 = int((l1 == 4).sum())
        text(ctx, '2 heart themes', bx + bw/2, by + 90, 36, INK, 'b')
        col(ctx, hx(GROUPS[0][1])); ctx.arc(bx + 60, by + 200, 16, 0, 6.29); ctx.fill()
        text(ctx, 'Heart and blood pressure', bx + 92, by + 192, 24, INK, 'b', 'l')
        text(ctx, f'{n3:,} studies', bx + 92, by + 228, 24, GREY2, 'm', 'l')
        col(ctx, hx(GROUPS[1][1])); ctx.arc(bx + 60, by + 320, 16, 0, 6.29); ctx.fill()
        text(ctx, 'High blood pressure', bx + 92, by + 312, 24, INK, 'b', 'l')
        text(ctx, 'in pregnancy', bx + 92, by + 346, 24, INK, 'b', 'l')
        text(ctx, f'{n4:,} studies', bx + 92, by + 382, 24, GREY2, 'm', 'l')
        text(ctx, 'The heart in general, and', bx + bw/2, by + 500, 24, INK, 'm')
        text(ctx, 'the heart in pregnancy', bx + bw/2, by + 536, 24, INK, 'm')
    surf.write_to_png(out)

if __name__ == '__main__':
    draw(int(sys.argv[1]), sys.argv[2])
