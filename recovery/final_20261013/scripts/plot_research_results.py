"""Publication-style plots from actual frozen artifacts only."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':12,'axes.linewidth':1.5,
    'axes.spines.top':False,'axes.spines.right':False,'legend.frameon':False,'svg.fonttype':'none','pdf.fonttype':42})
OUT=Path('figures');OUT.mkdir(exist_ok=True)
COLORS={'full':'#767676','transition':'#0F4D92','learned_stop':'#42949E','eat':'#8BCF8B',
    'conformal_thinking':'#9A4D8E','fixed0':'#CFCECE','fixed1024':'#B64342','random':'#E9A6A1',
    'value_outcome':'#C3A353','value_frequency':'#5296C7','value_cheap':'#A67B52','matched_stop':'#325B55'}
NAMES={'full':'FULL','transition':'Value controller','learned_stop':'Learned correctness','eat':'EAT',
    'conformal_thinking':'Dual threshold','fixed0':'Zero thinking','fixed1024':'Fixed 1024','random':'Random',
    'value_outcome':'Marginal values','value_frequency':'Alternate frequency','value_cheap':'Cheap features','matched_stop':'Matched correctness'}


def export(fig,name):
    fig.tight_layout(pad=1.4)
    for extension in ['png','pdf','svg']:fig.savefig(OUT/f'{name}.{extension}',dpi=300,facecolor='white',bbox_inches='tight')
    plt.close(fig)


def wilson(k,n):
    z=1.96;p=k/n;denominator=1+z*z/n
    center=(p+z*z/(2*n))/denominator
    radius=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
    return 100*(center-radius),100*(center+radius)


stats_path=Path('results/analysis/online_statistics.json')
if not stats_path.exists():raise SystemExit('Missing actual online statistics; no placeholder plots')
stats=json.loads(stats_path.read_text(encoding='utf-8'))
assert stats['models'],'No actual online model results'
for model,data in stats['models'].items():
  for cohort_name,cohort in data['cohorts'].items():
    fig,axes=plt.subplots(1,3,figsize=(13.2,4.6),gridspec_kw={'width_ratios':[1,1,0.75]})
    legend=axes[2];legend.set_axis_off();handles=[]
    for method,row in cohort['methods'].items():
        assert row['n']==cohort['n'],'Do not overlay unmatched cohorts'
        n=row['n'];accuracy=100*row['accuracy'];low,high=wilson(row['correct'],n)
        color=COLORS.get(method,'#272727');marker='*' if method=='transition' else 'o'
        for axis,x in zip(axes[:2],[row['mean_tokens'],row['mean_wall_ms']/1000]):
            handle=axis.errorbar(x,accuracy,yerr=[[max(0,accuracy-low)],[max(0,high-accuracy)]],fmt=marker,
                markersize=12 if marker=='*' else 7,color=color,ecolor=color,capsize=3,elinewidth=1.2)
        handles.append((handle,NAMES.get(method,method)+f' (n={n})'))
    axes[0].set_xscale('log');axes[0].set_xlabel('Mean generated tokens (log scale)')
    axes[1].set_xlabel('Mean wall-clock time (s)')
    for axis in axes[:2]:axis.set_ylabel('Accuracy (%)');axis.set_ylim(0,103)
    legend.legend([x[0] for x in handles],[x[1] for x in handles],loc='center',fontsize=10)
    fig.suptitle(model+' | '+cohort_name+' | same questions for every method',fontsize=13)
    fig.text(0.03,-0.03,'95% Wilson accuracy intervals. Time includes runtime decisions. Every point uses the same question cohort.',fontsize=9)
    export(fig,'online_quality_cost_'+model+'_'+cohort_name)
  comparisons=data['comparisons'];keys=[k for k in comparisons if k.startswith('transition_vs_')]
  if keys:
        fig,axes=plt.subplots(1,3,figsize=(13.6,5.6))
        for axis,metric,label,scale in zip(axes,['accuracy_delta','token_saving','wall_saving'],
            ['Accuracy difference (pp)','Token saving (%)','Wall-clock saving (%)'],[100,100,100]):
            for i,key in enumerate(keys):
                row=comparisons[key];value=scale*row[metric];low,high=np.asarray(row['bootstrap_95ci'][metric])*scale
                axis.errorbar(value,i,xerr=[[max(0,value-low)],[max(0,high-value)]],fmt='o',color='#0F4D92',capsize=3)
            axis.axvline(0,color='#767676',linewidth=1,linestyle='--');axis.set_xlabel(label)
            axis.set_yticks(range(len(keys)),[NAMES.get(k.removeprefix('transition_vs_'),k)+f" (n={comparisons[k]['n']})" for k in keys],fontsize=9)
        fig.suptitle(model+' | question-paired bootstrap, 95% CI',fontsize=13)
        export(fig,'paired_gain_'+model)
print('Exported actual online figures',len(list(OUT.glob('*.png'))))
