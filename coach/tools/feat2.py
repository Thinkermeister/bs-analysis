"""bsfeat.js と同じ定義の特徴量（Python版）。"""
import json
from features import parse_notes, info_params
ANG = {0: 90, 1: 270, 2: 180, 3: 0, 4: 135, 5: 45, 6: 225, 7: 315}
def angdiff(a,b):
    d=abs(a-b)%360; return 360-d if d>180 else d
def feat(dat, info_txt, ch, df):
    bpm,njs,off=info_params(info_txt,ch,df)
    notes,bombs,chains,arcs=parse_notes(dat)
    if len(notes)<10: return None
    sec=lambda b:b*60/bpm; dur=max(sec(notes[-1][0])-sec(notes[0][0]),1e-6); N=len(notes)
    sw={0:[],1:[]}
    for c in (0,1):
        h=[n for n in notes if n[3]==c]; i=0
        while i<len(h):
            g=[h[i]]
            while i+1<len(h) and h[i+1][0]-g[0][0]<0.0626: i+=1; g.append(h[i])
            sw[c].append(g); i+=1
    gaps=fr=fast=0
    for c in (0,1):
        s=sw[c]
        for a,b in zip(s,s[1:]):
            g=sec(b[0][0])-sec(a[0][0])
            if g<=0: continue
            gaps+=1; fast+= g<0.25
            da=next((n[4] for n in a if n[4] in ANG),None); db=next((n[4] for n in b if n[4] in ANG),None)
            if da is not None and db is not None and g<0.3 and angdiff(ANG[da],ANG[db])>=135: fr+=1
    from collections import Counter
    cnt=Counter((round(n[0]*100)/100,n[3]) for n in notes)
    r=lambda x:round(x,3)
    return dict(nps=r(N/dur),sps=r((gaps+2)/dur),play=round(dur),notes=N,njs=njs,chains=chains,arcs=arcs,bombs=len(bombs),
        cross=r(sum(1 for n in notes if (n[3]==0 and n[1]>=2) or (n[3]==1 and n[1]<=1))/N),
        frev=r(fr/max(1,gaps)),fast=r(fast/max(1,gaps)),
        bup=r(sum(1 for n in notes if n[2]==0 and n[4] in (0,4,5))/N),
        sbsc=r(sum(v for v in cnt.values() if v>=2)/N),left=r(sum(1 for n in notes if n[3]==0)/N))
if __name__=='__main__':
    M=json.load(open('ss_star03_maps_20261125.json'))['maps']; out={}
    for h,m in M.items():
        for k,dat in (m.get('diffs') or {}).items():
            ch,df=k.split('/')
            try: out.setdefault(h.upper(),{})[k]=feat(dat,m['info'],ch,df)
            except Exception as e: out.setdefault(h.upper(),{})[k]='err:'+str(e)
    json.dump(out,open('feat_star03_v2.json','w'))
    print(out['52891D412CB99D01D13CF462A40EDA2218F0B07C']['Standard/Normal'])
