import math
def qpt(p0,c,p1,t):
    return tuple((1-t)**2*p0[i]+2*(1-t)*t*c[i]+t*t*p1[i] for i in range(2))
def qder(p0,c,p1,t):
    return tuple(2*(1-t)*(c[i]-p0[i])+2*t*(p1[i]-c[i]) for i in range(2))
def offset(p0,c,p1,d,t0=0,t1=1,n=24,side=1):
    pts=[]
    for k in range(n+1):
        t=t0+(t1-t0)*k/n
        x,y=qpt(p0,c,p1,t); dx,dy=qder(p0,c,p1,t); L=math.hypot(dx,dy)
        nx,ny=-dy/L*side, dx/L*side
        pts.append((x+nx*d,y+ny*d))
    return 'M'+' L'.join(f'{x:.2f} {y:.2f}' for x,y in pts)
# geometry
LA=((36,10),(44,42),(60,58))   # under collar (viewer's left), extends above neckline y=20, clipped
RA=((84,10),(77,44),(48,67))   # over collar
W=7; DW=2.2; GAP=7.4         # band width, 동정 width, centre distance
def mark(simple=False, color='#4E7A70', bg=None, size=120):
    s=[f'<svg width="{size}" height="{size}" viewBox="0 0 120 120" fill="none" stroke-linecap="round">']
    s.append('<defs><clipPath id="nk"><rect x="0" y="20" width="120" height="100"/></clipPath>'
             f'<mask id="cut"><rect width="120" height="120" fill="white"/><path d="{offset(*RA,0)}" stroke="black" stroke-width="{W+6}" stroke-linecap="butt"/></mask></defs>')
    s.append(f'<g clip-path="url(#nk)" stroke="{color}">')
    # under collar band + 동정 (neck side = right of travel for left arm => side=-1)
    s.append(f'<g mask="url(#cut)"><path d="{offset(*LA,0)}" stroke-width="{W}"/>')
    if not simple: s.append(f'<path d="{offset(*LA,GAP,0,0.62,side=-1)}" stroke-width="{DW}"/>')
    s.append('</g>')
    s.append(f'<path d="{offset(*RA,0)}" stroke-width="{W}"/>')
    if not simple: s.append(f'<path d="{offset(*RA,GAP,0,0.78,side=1)}" stroke-width="{DW}"/>')
    s.append('</g>')
    s.append(f'<path d="M32 81 Q32 94 41 94 L79 94 Q88 94 88 81" stroke="{color}" stroke-width="{W}" stroke-linejoin="round"/>')
    s.append('</svg>')
    return ''.join(s)
if __name__=='__main__':
    import sys
    pal={'하엽 녹청':'#4E7A70','청자 비색':'#6F9A8C','쪽빛 먹청':'#2F4F4A'}
    rows=[]
    for bgname,bg,fg in (('한지','#F4EFE3',None),('먹','#1B2120',None)):
        cells=[]
        for nm,c in pal.items():
            cc = c if bg!='#1B2120' else {'#4E7A70':'#8DB3A7','#6F9A8C':'#A9C7BC','#2F4F4A':'#C9DAD4'}[c]
            cells.append(f'<div style="display:flex;align-items:flex-end;gap:16px;margin:10px 0"><span style="width:70px;font-size:12px;color:{"#555" if bg!="#1B2120" else "#aaa"}">{nm}</span>{mark(color=cc,size=150)}{mark(color=cc,size=64)}{mark(simple=True,color=cc,size=32)}<span style="display:flex;align-items:center;gap:8px;font:700 28px \'Apple Myungjo\',serif;color:{cc};letter-spacing:.08em">{mark(color=cc,size=44)}매무시</span></div>')
        rows.append(f'<div style="background:{bg};padding:16px">{"".join(cells)}</div>')
    open(sys.argv[1],'w').write('<!doctype html><meta charset=utf-8><body style="margin:0;font-family:-apple-system">'+''.join(rows))
