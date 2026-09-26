#!/usr/bin/env python3
"""Rebuild saved-data comparison: Python 3 + matplotlib. Does not access hardware."""
import json
import math
from pathlib import Path
import subprocess
import tempfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts'
config = json.loads((ROOT / 'config.json').read_text())
inputs = ['apple-auto-before.json', 'after-initial-install.json', 'current-hardware.json',
          'after-failed-live-check.json', 'after-stall-failure.json']
raw = [(filename, json.loads((OUT / filename).read_text())) for filename in inputs]
raw.append(('live-report.json/observations/1', json.loads((OUT / 'live-report.json').read_text())['observations'][1]))


def fraction(temperature, curve):
    if temperature <= curve[0]['temperature']:
        return curve[0]['fraction']
    for a, b in zip(curve, curve[1:]):
        if temperature <= b['temperature']:
            return a['fraction'] + (b['fraction']-a['fraction']) * (temperature-a['temperature']) / (b['temperature']-a['temperature'])
    return curve[-1]['fraction']


def requested(demand, minimum, maximum):
    floor = max(config['baselineRPM'], minimum)
    return math.floor(floor + (maximum-floor)*demand + .5)


samples = []
for source, sample in raw:
    v = sample['values']
    assert sample['model'] == config['model']
    assert all(v[f'F{i}Md'] in [0, 3] for i in range(2)), source
    temps = {group: max(v[k] for k in config[group+'Keys']) for group in ['cpu','gpu','palm']}
    chip = max(temps['cpu'], temps['gpu'])
    demand = max(fraction(chip, config['curve']), fraction(temps['palm'], config['palmCurve']))
    # These samples can be placed on the CPU/GPU curve because palm demand is lower.
    assert fraction(chip, config['curve']) >= fraction(temps['palm'], config['palmCurve'])
    samples.append({'source': source, 'time': sample['time'], **temps, 'chip_temperature': chip,
                    'apple_target_rpm': [v[f'F{i}Tg'] for i in range(2)],
                    'apple_actual_rpm': [v[f'F{i}Ac'] for i in range(2)],
                    'minimum_rpm': [v[f'F{i}Mn'] for i in range(2)],
                    'maximum_rpm': [v[f'F{i}Mx'] for i in range(2)],
                    'cooler_curve_rpm': [requested(demand, v[f'F{i}Mn'], v[f'F{i}Mx']) for i in range(2)]})

# Verify calculated counterfactual targets against the existing controller's replay.
# Each sample is a fresh process so rate-limited falling targets cannot carry over.
with tempfile.TemporaryDirectory(prefix='cooler-curve-replay-') as temp:
    frame_path = Path(temp) / 'frames.json'
    for s in samples:
        frame_path.write_text(json.dumps([{**{key:s[key] for key in ['cpu','gpu','palm']},
            'minRPM':s['minimum_rpm'], 'maxRPM':s['maximum_rpm'], 'elapsed':2}]))
        result = subprocess.run([str(ROOT/'build/cooler'), 'replay', str(ROOT/'config.json'), str(frame_path)],
                                check=True, capture_output=True, text=True)
        decision = json.loads(result.stdout)
        assert decision['targets'] == s['cooler_curve_rpm'], (s, decision)

reference = samples[0]
blue, orange, ink, muted, grid = '#1D6388', '#B86521', '#263440', '#586670', '#DCE3E6'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'text.color':ink,
    'axes.labelcolor':muted,'xtick.color':muted,'ytick.color':muted,'axes.edgecolor':grid,
    'svg.fonttype':'none'})
fig, axes = plt.subplots(1, 2, figsize=(12.4, 6.8), sharey=True)
fig.set_facecolor('#FAFBFC')
fig.subplots_adjust(left=.08,right=.97,bottom=.29,top=.72,wspace=.16)
fig.text(.08,.94,'Cooler vs Apple automatic',fontsize=23,fontweight='bold',ha='left')
fig.text(.08,.892,'Your M1 Max MacBook Pro · installed profile and six saved automatic-mode snapshots',fontsize=11,color=muted)
fig.legend(handles=[Line2D([0],[0],color=blue,lw=2.5,label='Cooler: configured target'),
                    Line2D([0],[0],color=orange,marker='D',linestyle='none',markersize=6,label='Apple: observed automatic target')],
           loc='upper left',bbox_to_anchor=(.075,.858),frameon=False,ncol=2,columnspacing=2)
x = list(range(40, 91))
for i, ax in enumerate(axes):
    ax.set_facecolor('#FAFBFC')
    minimum, maximum = reference['minimum_rpm'][i], reference['maximum_rpm'][i]
    y = [requested(fraction(t,config['curve']),minimum,maximum) for t in x]
    ax.plot(x,y,color=blue,lw=2.8,zorder=3)
    ax.scatter([p['temperature'] for p in config['curve']],
               [requested(p['fraction'],minimum,maximum) for p in config['curve']],
               color=blue,s=25,zorder=4)
    ax.scatter([s['chip_temperature'] for s in samples], [s['apple_target_rpm'][i] for s in samples],
               color=orange,marker='D',s=40,edgecolors='#FAFBFC',linewidths=.65,zorder=5)
    t, ours, apple = reference['chip_temperature'], reference['cooler_curve_rpm'][i], reference['apple_target_rpm'][i]
    ax.plot([t,t],[apple,ours],color=muted,lw=1,ls=(0,(2,3)),zorder=2)
    ax.scatter([t],[ours],s=62,facecolor='#FAFBFC',edgecolor=blue,lw=1.8,zorder=6)
    ax.text(t+1.6,(apple+ours)/2, f'{ours/apple:.2f}× RPM\nat {t:.1f}°C',fontsize=10.5,ha='left',va='center',color=ink)
    ax.annotate(f'{ours:,}',(t,ours),xytext=(-8,12),textcoords='offset points',ha='right',color=blue,fontweight='bold')
    ax.text(87.8,apple-330,f'{apple:,} RPM',color=orange,ha='right',fontsize=10)
    ax.set_title(['Left fan','Right fan'][i],loc='left',fontsize=13,fontweight='bold',pad=13)
    ax.set_xlim(40,90); ax.set_ylim(0,6700)
    ax.set_xticks([45,55,65,75,85]); ax.set_yticks([0,1800,3000,4500,6000])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda val,pos:f'{int(val):,}'))
    ax.set_xlabel('Hottest configured CPU / GPU sensor (°C)',labelpad=12)
    ax.grid(axis='y',color=grid,linewidth=.8,zorder=0)
    ax.spines[['top','right','left']].set_visible(False)
    ax.tick_params(axis='both',length=0,pad=8)
axes[0].set_ylabel('Requested fan speed (RPM)',labelpad=12)
fig.text(.08,.175,'How to read this',fontsize=11,fontweight='bold')
fig.text(.08,.14,'Apple dots cover about 70–82°C, including readings after returning to automatic mode.',fontsize=10,color=muted)
fig.text(.08,.108,'They do not establish Apple’s full curve or a temperature improvement. No Apple curve has been fitted.',fontsize=10,color=muted)
fig.text(.08,.065,'Cooler also raises speeds for warm palms; gradual slowdown can keep targets above the blue lines.',fontsize=10,color=muted)
fig.text(.08,.033,'Saved readings: 26 Sep 2026, 20:51–21:21 UTC. Blue values verified against Cooler’s read-only replay.',fontsize=8.5,color=muted)
fig.savefig(OUT/'curve-comparison.png',dpi=180,facecolor=fig.get_facecolor())
fig.savefig(OUT/'curve-comparison.svg',facecolor=fig.get_facecolor())
plt.close(fig)
(OUT/'curve-comparison-data.json').write_text(json.dumps({'model':config['model'],'config':config,'samples':samples,
    'reference_time':reference['time'],'replay_verified':True,'apple_curve_known':False,
    'scope':'Recorded automatic-mode targets versus configured Cooler targets at matching temperatures; not a controlled cooling or noise benchmark.'},indent=2)+'\n')
print(json.dumps({'sample_count':len(samples),'reference':reference,'replay_verified':True},indent=2))
