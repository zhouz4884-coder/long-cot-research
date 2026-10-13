"""Exploratory calibration of already observed terminal STOPs, never selection."""
import csv,hashlib,json,math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'results/next_phase_20261013/ALL_TERMINAL_CASES.json'
rows=json.loads(source.read_text(encoding='utf-8'))
stop=[r for r in rows if r['model']=='Qwen3-4B' and r['last_action']=='STOP']
assert len(stop)==211
OUT=ROOT/'figures/next_phase_20261013';OUT.mkdir(exist_ok=True,parents=True)
plt.rcParams.update({'font.family':['Arial','DejaVu Sans'],'font.size':11,'axes.linewidth':1.4,
 'axes.spines.top':False,'axes.spines.right':False,'legend.frameon':False,
 'pdf.fonttype':42,'svg.fonttype':'none','savefig.dpi':300})

def interval(h,n):
    z=1.959963984540054;p=h/n;d=1+z*z/n
    c=(p+z*z/(2*n))/d;r=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return c-r,c+r

def bins(score,target,edges):
    result=[]
    for lo,hi in zip(edges[:-1],edges[1:]):
        selected=[r for r in stop if lo<=r[score]<hi or (hi==1 and r[score]==1)]
        if not selected:continue
        n=len(selected);h=sum(r[target] for r in selected);l,u=interval(h,n)
        result.append({'lo':lo,'hi':hi,'n':n,'event_n':h,'prediction_mean':sum(r[score] for r in selected)/n,
                       'observed_rate':h/n,'wilson95':[l,u]})
    return result

specs=[('p_stop','controller_correct',[0,.5,.9,.95,1],
        'A   Candidate correctness','Predicted correctness','Observed correctness'),
       ('p_full_fix','harm',[0,.05,.1,.15,.2,1],
        'B   STOP harm relative to FULL','Predicted harmful STOP probability','Observed harmful STOP rate')]
fig,axs=plt.subplots(1,2,figsize=(10,4.5))
records={}
for ax,(score,target,edges,title,xlabel,ylabel) in zip(axs,specs):
    b=bins(score,target,edges);records[score]=b
    x=np.array([r['prediction_mean'] for r in b]);y=np.array([r['observed_rate'] for r in b])
    low=np.array([r['wilson95'][0] for r in b]);high=np.array([r['wilson95'][1] for r in b])
    ax.plot([0,1],[0,1],ls='--',lw=1.2,color='#767676',label='Identity')
    ax.errorbar(x,y,yerr=np.vstack([y-low,high-y]),fmt='o',color='#0F4D92',capsize=4,
                ms=6,lw=1.5,label='Observed (95% Wilson)')
    for xi,yi,r in zip(x,y,b):ax.annotate(f"n={r['n']}",(xi,yi),xytext=(6,8),textcoords='offset points',fontsize=9)
    ax.set(xlim=(-.02,1.03),ylim=(-.03,1.08),xlabel=xlabel,ylabel=ylabel,title=title)
axs[0].legend(loc='lower right',fontsize=9)
axs[1].set(xlim=(-.01,.43),ylim=(-.025,.8))
fig.text(.5,.015,'Qwen3-4B: 211 selected terminal STOPs; already observed test; exploratory diagnosis only.',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.07,1,1),pad=1.3)
for suffix in ['png','pdf','svg']:
    target=OUT/f'legacy_terminal_risk_reliability.{suffix}'
    fig.savefig(target)
    if suffix=='svg':
        target.write_text('\n'.join(line.rstrip() for line in target.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8',newline='\n')
plt.close(fig)
strata=[]
for group,fn in [
 ('checkpoint_tokens',lambda r:'<512' if r['last_offset']<512 else '512-2047' if r['last_offset']<2048 else '>=2048'),
 ('difficulty',lambda r:'1-3' if r['level']<=3 else '4-5'),
 ('remaining_reference_tokens',lambda r:'<512' if r['reference_remaining_think_tokens']<512 else '512-2047' if r['reference_remaining_think_tokens']<2048 else '>=2048'),
 ('reference_censoring',lambda r:'censored' if r['full_censored'] else 'natural_end'),
 ('subject',lambda r:r['subject'])]:
    for key in sorted({fn(r) for r in stop}):
        subset=[r for r in stop if fn(r)==key];n=len(subset);h=sum(r['harm'] for r in subset)
        l,u=interval(h,n)
        strata.append({'group':group,'stratum':key,'n':n,'harms':h,'benefits':sum(r['benefit'] for r in subset),
                       'harm_rate':h/n,'harm_wilson_lo':l,'harm_wilson_hi':u,
                       'mean_predicted_harm':sum(r['p_full_fix'] for r in subset)/n})
csvpath=ROOT/'results/next_phase_20261013/STOP_RISK_STRATA.csv'
with csvpath.open('w',encoding='utf-8',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(strata[0]));writer.writeheader();writer.writerows(strata)
report={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'n':211,'bins':records,'strata':strata,
 'scope':'Already observed selected terminal STOPs only; descriptive intervals do not certify a newly selected policy.',
 'figure_conclusion':'Current correctness confidence and relative harmful STOP risk are distinct; sparse bins have wide uncertainty.'}
(ROOT/'results/next_phase_20261013/RISK_RELIABILITY_FIGURE_DATA.json').write_text(json.dumps(report,indent=2)+'\n')
print('Created three figure formats and the source table; selected STOP n=211.')
