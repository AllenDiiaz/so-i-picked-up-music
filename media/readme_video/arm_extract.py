import cv2, numpy as np
im = cv2.imread('/root/.claude/uploads/4f0045de-265e-50a4-a7ff-ee284bf0416f/d93312fc-image.png', cv2.IMREAD_UNCHANGED)
al = im[..., 3:4].astype(np.float32)/255
rgb = (im[..., :3].astype(np.float32) * al + 255 * (1 - al)).astype(np.uint8)
g0 = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
band = np.zeros(g0.shape, np.uint8)
cv2.rectangle(band, (574, 695), (766, 881), 255, 13)
cv2.line(band, (766, 695), (1112, int(669 - 0.79 * 312)), 255, 11)
cv2.line(band, (766, 881), (1112, int(908 + 0.78 * 312)), 255, 11)
O = ((g0 > 100) & (g0 < 200) & (band == 0)).astype(np.uint8)          # outline (and its anti-aliasing)
R = cv2.dilate(band, np.ones((17, 17), np.uint8))                     # zone where the outline gets redrawn
remove = ((R > 0) & ((O > 0) | (band > 0))).astype(np.uint8) * 255
remove = cv2.dilate(remove, np.ones((3, 3), np.uint8))
clean = cv2.inpaint(rgb, remove, 9, cv2.INPAINT_TELEA)
src = ((g0 > 100) & (g0 < 178) & (R == 0)).astype(np.uint8)          # outline pixels just outside the zone
# endpoints: outline pixels touching the redraw zone; join pairs with Hermite curves
touch = src & cv2.dilate((R > 0).astype(np.uint8), np.ones((5, 5), np.uint8))
n, lab, st, cen = cv2.connectedComponentsWithStats(cv2.dilate(touch, np.ones((5, 5), np.uint8)))
ends = []
for i in range(1, n):
    c = cen[i]; ys, xs = np.nonzero(src[int(c[1]) - 14:int(c[1]) + 15, int(c[0]) - 14:int(c[0]) + 15])
    if len(xs) < 6: continue
    P = np.c_[xs + int(c[0]) - 14, ys + int(c[1]) - 14].astype(float); mu = P.mean(0)
    d = np.linalg.svd(P - mu)[2][0]
    # point the tangent into the zone
    probe = c + d * 10
    if R[int(np.clip(probe[1], 0, R.shape[0]-1)), int(np.clip(probe[0], 0, R.shape[1]-1))] == 0: d = -d
    ends.append((c, d))
used = set(); layer = np.zeros(g0.shape, np.uint8)
for i, (c1, d1) in enumerate(ends):
    if i in used: continue
    best, bj = 1e9, -1
    for j, (c2, d2) in enumerate(ends):
        if j == i or j in used: continue
        v = c2 - c1; L = np.linalg.norm(v)
        if L > 60 or L < 4: continue
        score = L * (2 - np.dot(d1, v / L) - np.dot(-d2, v / L))
        if np.dot(d1, v / L) > 0.6 and np.dot(-d2, v / L) > 0.6 and score < best: best, bj = score, j
    if bj < 0: continue
    used |= {i, bj}; c2, d2 = ends[bj]; L = np.linalg.norm(c2 - c1)
    tt = np.linspace(0, 1, 60)[:, None]
    h00, h10, h01, h11 = 2*tt**3-3*tt**2+1, tt**3-2*tt**2+tt, -2*tt**3+3*tt**2, tt**3-tt**2
    pts = h00 * c1 + h10 * d1 * L + h01 * c2 + h11 * (-d2) * L
    cv2.polylines(layer, [np.round(pts * 4).astype(np.int32)], False, 255, 2, cv2.LINE_AA, shift=2)
print("ends", len(ends), "pairs", len(used) // 2)
lay = (layer.astype(np.float32) / 255)[..., None]
OUTC = np.array([138, 138, 138], np.float32)
sm = clean.copy()
for _ in range(4): sm = cv2.medianBlur(sm, 11)
zone = cv2.GaussianBlur((R > 0).astype(np.float32), (9, 9), 0)[..., None]
clean = (clean.astype(np.float32) * (1 - zone) + sm.astype(np.float32) * zone).astype(np.uint8)
out = (clean.astype(np.float32) * (1 - lay) + OUTC * lay).astype(np.uint8)
c = cv2.flip(out[440:1190, 130:1010], 1)
g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
bg = (g >= 250).astype(np.uint8)
n, lab = cv2.connectedComponents(bg)
edge_labels = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
outside = np.isin(lab, [L for L in edge_labels if L != 0 or bg[lab == 0].all()]) & (bg > 0)
alpha = np.where(outside, 0, 255).astype(np.uint8); alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
cv2.imwrite('arm/bio_arm.png', np.dstack([c, alpha]))
cv2.imwrite('arm/bio_small.png', cv2.resize(c, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
z = out[440:1190, 130:1010][200:560, 400:800]; cv2.imwrite('arm/bio_zoom4.png', cv2.resize(z, None, fx=2, fy=2))
