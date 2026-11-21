from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
import numpy as np,json,wave,math,subprocess,functools,bisect
import mouths
import os
R=Path(__file__).resolve().parent;P=R.parent;W,H,FPS=1280,720,24
TL=json.loads((R/'revoice-swapped/timeline.json').read_text());T=TL['turns']
D=math.ceil(TL['duration']*24)/24;N=round(D*24)
with wave.open(str(R/'revoice-swapped/analysis.wav'),'rb') as w:
 sr=w.getframerate();audio=w.readframes(w.getnframes())
audio=audio[:N*1000*2]+bytes(max(0,N*1000*2-len(audio)))
x=np.frombuffer(audio,dtype='<i2').astype(np.float32)/32768
assert len(x)==N*1000
rms=np.sqrt(np.mean(x.reshape(N,1000)**2,axis=1));smooth=np.convolve(rms,[.18,.64,.18],mode='same')
states=np.zeros(N,dtype=int);speakers=np.zeros(N,dtype=int)
for turn in T:
 a=math.ceil(turn['start']*24);b=min(N,math.floor(turn['end']*24))
 scale=max(.035,float(np.percentile(rms[a:b],92)))
 v=np.clip((smooth[a:b]-.006)/(scale-.006),0,1)**.72
 states[a:b]=np.where(rms[a:b]<.006,0,np.clip(np.rint(v*7),1,7)).astype(int)
 speakers[a:b]=1 if turn['speaker']=='A' else 2
np.save(R/'revoice-swapped/revoice-mouth-states.npy',states)
@functools.lru_cache(None)
def ft(n):return ImageFont.truetype(os.environ.get('PVK_FONT', '/System/Library/Fonts/AppleSDGothicNeo.ttc'),n)
def text(d,xy,s,n=28,c='white',a=None):d.text(xy,s,font=ft(n),fill=c,anchor=a)
def rr(d,box,c,r=15):d.rounded_rectangle(box,radius=r,fill=c)
def wrap(s,width,n=28):
 out=[];line=''
 for c in s:
  if ft(n).getlength(line+c)>width:out.append(line.strip());line=c
  else:line+=c
 if line:out.append(line.strip())
 return out
cues=json.loads((R/'revoice-swapped/captions.json').read_text())
@functools.lru_cache(None)
def subpage(k):
 im=Image.new('RGBA',(W,108),(0,0,0,0));d=ImageDraw.Draw(im)
 if k<0:return im
 c=cues[k];rr(d,(28,18,75,59),'#65b6a0' if c['speaker']=='A' else '#e7a56c',10)
 text(d,(51,24),c['speaker'],25,'#172421','ma')
 ls=wrap(c['text'],1120);assert len(ls)<=2
 for j,line in enumerate(ls):text(d,(108,10+j*38 if len(ls)>1 else 28),line)
 return im
cs=[c['start'] for c in cues]

def txt(d,xy,s,n=28,c='#203c36',a=None):d.text(xy,s,font=ft(n),fill=c,anchor=a)

def clamp(x):return min(1.,max(0.,x))

def ease(x):x=clamp(x);return x*x*(3-2*x)

def chip(d,x,y,s,fill='#fff2d7',n=26):
    w=ft(n).getlength(s)+36
    rr(d,(x-w/2,y-7,x+w/2,y+n+13),fill,12,outline='#c5a875')
    txt(d,(x,y),s,n,'#233c35','ma')

def token(im,x,y,s,fill='#367a69',size=92,alpha=255):
    layer=Image.new('RGBA',(size+14,size+14),(0,0,0,0));d=ImageDraw.Draw(layer)
    rr(d,(9,12,size+9,size+12),(22,33,25,50),12)
    rr(d,(2,2,size+2,size+2),fill,12,outline='#d7b461',width=3)
    txt(d,(size/2+2,size/2+2),s,32,'#fff8df','mm')
    if alpha<255:layer.putalpha(layer.getchannel('A').point(lambda a:round(a*alpha/255)))
    im.alpha_composite(layer,(round(x-size/2),round(y-size/2)))

def original_concept(sc,t):
    kind=sc['kind'];idx=['function','map','fold','overview'].index(kind)
    im=ART[idx].copy().convert('RGBA');d=ImageDraw.Draw(im)
    # Keep the generated objects dominant; all precise labels are post-production.
    rr(d,(38,19,1242,81),(251,243,225,242),16,outline='#cbb18a')
    txt(d,(640,30),sc['title'],30,'#233c35','ma')
    u=clamp((t-sc['start']-1)/(sc['end']-sc['start']-2))
    if kind=='overview':
        for x,label in [(220,'일급 함수'),(640,'map'),(1090,'fold')]:chip(d,x,465,label,n=29)
        for x in [450,860]:txt(d,(x,480),'→',42,'#376d5f','mm')
        chip(d,640,540,'함수를 값으로 → 원소마다 변환 → 하나로 누적',n=26)
    elif kind=='function':
        for x,label in [(254,'함수 값'),(621,'변수에 저장'),(1010,'함수의 인자로')]:chip(d,x,456,label)
        # A reusable value travels to storage, pauses, then goes to the receiver.
        if u<.42:v=ease(u/.42);x=254+(621-254)*v
        elif u<.58:x=621
        else:v=ease((u-.58)/.42);x=621+(1010-621)*v
        y=310-45*math.sin(u*2*math.pi)**2
        token(im,x,y,'fn',size=100)
        d=ImageDraw.Draw(im);chip(d,640,537,'같은 함수를 저장하고 전달해요',n=27)
    elif kind=='map':
        # Every input transforms independently; no sum is used in this scene.
        inputs=[70,80,90];outs=[75,85,95]
        ix=[121,254,389];ox=[891,1028,1163]
        pos=u*3.35
        chip(d,640,125,'+5',fill='#376f5e',n=32)
        # redraw label light for dark badge
        txt(d,(640,125),'+5',32,'#fff4d9','ma')
        for j,(a,b) in enumerate(zip(inputs,outs)):
            p=clamp(pos-j)
            if p<.02:txt(d,(ix[j],324),str(a),40,'#354d42','mm')
            elif p>=1:txt(d,(ox[j],324),str(b),40,'#354d42','mm')
            else:
                x=ix[j]+(ox[j]-ix[j])*ease(p)
                token(im,x,324-105*math.sin(math.pi*p),str(a if p<.5 else b),fill='#387e6b' if p<.5 else '#b4863e',size=86)
        d=ImageDraw.Draw(im);chip(d,640,531,'[70, 80, 90]  →  map(+5)  →  [75, 85, 95]',n=27)
    elif kind=='fold':
        inputs=[70,80,90];ix=[125,265,407];pos=u*3.4
        # Addition starts from zero and consumes the ORIGINAL scores, not map outputs.
        done=min(3,int(pos));sums=[0,70,150,240];acc=sums[done]
        for j,a in enumerate(inputs):
            p=clamp(pos-j)
            if p<.02:txt(d,(ix[j],362),str(a),38,'#354d42','mm')
            elif p<1:token(im,ix[j]+(525-ix[j])*ease(p),362,str(a),size=84)
        d=ImageDraw.Draw(im)
        txt(d,(724,332),'누적 합계',24,'#546359','mm')
        txt(d,(724,390),str(acc),64,'#243f37','mm')
        if done==3:txt(d,(1117,366),'240',56,'#243f37','mm')
        chip(d,640,530,'초기값 0  →  70  →  150  →  240',n=28)
    return im


NEWART={n:ImageOps.fit(Image.open(R/'concepts-2-5'/(n+'.png')).convert('RGB'),(W,606),Image.Resampling.LANCZOS).convert('RGBA') for n in ['lambda','factory','filter','sort']}
def coord(x,y):return (round(x*W/600),round(y*W/600-57))
def oncard(d,x,y,label,n=32,color='#233c35'):
 txt(d,coord(x,y),label,n,color,'mm')
def concept(sc,t):
 kind=sc['kind']
 if kind not in NEWART:return original_concept(sc,t)
 im=NEWART[kind].copy();d=ImageDraw.Draw(im)
 rr(d,(38,19,1242,81),(251,243,225,245),16,outline='#cbb18a')
 txt(d,(640,30),sc['title'],30,'#233c35','ma')
 u=clamp((t-sc['start']-1)/(sc['end']-sc['start']-2))
 if kind=='lambda':
  oncard(d,138,220,'x + 5',32);oncard(d,317,230,'fn',36);oncard(d,460,226,'fn',36)
  chip(d,640,112,'lambda x: x + 5',n=34)
  stage=min(2,int(u*3));centers=[(138,220),(317,230),(460,226)]
  x,y=coord(*centers[stage]);d.rounded_rectangle((x-94,y-40,x+94,y+40),12,outline='#c59026',width=5)
  chip(d,640,535,['式 → 익명 함수 객체 생성','이름 없이 만든 함수도 값','함수 값을 다른 함수에 전달'][stage].replace('式','식'),n=29)
 elif kind=='factory':
  chip(d,640,112,'add_ten = make_adder(10)',n=32)
  oncard(d,357,190,'x + 10',30);oncard(d,490,223,'x + 10',27)
  x,y=coord(65,160);token(im,x,y,'10',fill='#b4863e',size=64)
  stage=min(2,int(u*3))
  d=ImageDraw.Draw(im)
  chip(d,640,535,['설정값 10을 전달','내부 함수를 결과로 반환','반환된 함수가 bonus = 10을 기억'][stage],n=29)
 elif kind=='filter':
  chip(d,640,112,'조건 함수: lambda x: x >= 80',n=29)
  for x,v in [(66,'70'),(138,'80'),(208,'90')]:oncard(d,x,134,v,38)
  oncard(d,454,101,'80',38);oncard(d,523,101,'90',38);oncard(d,470,206,'70',38)
  stage=min(2,int(u*3));cx=[66,138,208][stage];x,y=coord(cx,134)
  d.rounded_rectangle((x-54,y-49,x+54,y+49),12,outline='#bd7745' if stage==0 else '#3b957c',width=5)
  chip(d,640,535,['70: 조건 불충족 → 제외','80: 조건 충족 → 유지','결과: [80, 90] · 값 자체는 바꾸지 않음'][stage],n=28)
 elif kind=='sort':
  chip(d,640,112,'sorted(students, key=lambda s: s[1])',n=28)
  for x,y,label in [(51,157,'가:90'),(112,142,'나:70'),(184,164,'다:80'),(429,153,'나:70'),(490,153,'다:80'),(552,153,'가:90')]:oncard(d,x,y,label,24)
  oncard(d,327,160,'점수',25)
  chip(d,640,535,'이름·점수 묶음은 유지 · 점수를 기준으로 오름차순 정렬',n=26)
 return im

def presence(sc,t):
    # Fully absent during the core. Only transition edges contain a host inset.
    a=t-sc['start'];b=sc['end']-t
    if a<.95:return 1-ease(a/.95),'enter'
    if b<.8:return 1-ease(b/.8),'exit'
    return 0.,'absent'

def rr(d,b,c,r=14,outline=None,width=1):d.rounded_rectangle(b,radius=r,fill=c,outline=outline,width=width)
ART=[ImageOps.fit(Image.open(P/'concept-focus'/(n+'.jpg')).convert('RGB'),(W,606),Image.Resampling.LANCZOS) for n in ['function','map','fold','overview']]
SCENES=json.loads((R/'revoice-swapped/scenes.json').read_text())
TS=[t['start'] for t in T]
@functools.lru_cache(160)
def host(name,who,state):
 im=mouths.portrait(name,who,state)
 cw=im.width;ch=cw*606/W;y=(im.height-ch)*.14
 return im.transform((W,606),Image.Transform.EXTENT,(0,y,cw,y+ch),Image.Resampling.BICUBIC).convert('RGBA')
def shot(t,who):
 ti=max(0,bisect.bisect_right(TS,t)-1);seg=int((t-T[ti]['start'])/7)
 names=['wide','A_close','over_B','high'] if who=='A' else ['wide','B_threequarter','over_A','high']
 return names[(seg+ti)%4]
def render(i):
 t=i/24;who='A' if speakers[i]==1 else 'B' if speakers[i]==2 else None
 sc=next((s for s in SCENES if s['start']<=t<s['end']),None)
 visual_who={'A':'B','B':'A',None:None}[who]
 studio=host(shot(t,visual_who),visual_who,int(states[i]))
 if sc:
  image=concept(sc,t);visibility,phase=presence(sc,t)
  if visibility>0:
   edge=(t-sc['start'])/.95 if phase=='enter' else (sc['end']-t)/.8
   k=ease(edge);scale=1-.78*k;ww=round(W*scale);hh=round(606*scale)
   small=studio.resize((ww,hh),Image.Resampling.BILINEAR);small.putalpha(round(255*(1-clamp((k-.65)/.35))))
   image.alpha_composite(small,(round((W-ww-24)*k),round((606-hh-24)*k)))
 else:image=studio
 out=Image.new('RGBA',(W,H),'#172421');out.alpha_composite(image);d=ImageDraw.Draw(out)
 if not sc:
  ti=max(0,bisect.bisect_right(TS,t)-1)
  label='함수형 프로그래밍' if ti<7 else '01  일급 함수와 람다' if ti<21 else '02  고차 함수와 map' if ti<38 else '03  fold로 하나의 값 만들기' if ti<60 else '04  기출문제 복습과 정리'
  rr(d,(24,20,500,65),(17,30,27,220));text(d,(43,30),label,23,'#f7f1de')
  if who:rr(d,(1090,20,1256,65),(17,30,27,220));text(d,(1173,30),who+'  발화 중',21,'#f7f1de','ma')
 d.rectangle((0,604,W,608),fill='#b89d69')
 ci=bisect.bisect_right(cs,t)-1
 if ci>=0 and t>=cues[ci]['end']:ci=-1
 out.alpha_composite(subpage(ci),(0,608))
 d=ImageDraw.Draw(out);d.rectangle((0,716,W*t/D,720),fill='#c9aa6c')
 # Preserve the recording through its final sample; no imposed fade or added tail.
 return out.convert('RGB')
def timestamp(t):
 n=round(t*1000);h,n=divmod(n,3600000);m,n=divmod(n,60000);s,ms=divmod(n,1000)
 return f'{h:02}:{m:02}:{s:02},{ms:03}'
(R/'revoice-swapped/revoice.srt').write_text('\n\n'.join(f"{i+1}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['speaker']}: {c['text']}" for i,c in enumerate(cues)))
if __name__=='__main__':
 import sys,time
 sample='--sample' in sys.argv
 times=[1,12,27,58.98,244,260,334,360,710,745,930,1030,1230,1400,1768,1790]
 sheet=Image.new('RGB',(1280,720))
 for j,t in enumerate(times):
  im=render(round(t*24));sheet.paste(im.resize((320,180)),((j%4)*320,(j//4)*180))
 sheet.save(R/'revoice-swapped/storyboard.jpg',quality=94)
 if '--preview' in sys.argv:print('PREVIEW',D,N);raise SystemExit
 if sample:
  windows=[(0,15),(238,246),(329,334),(704,709),(925,930),(1256,1262),(1785,1791.36)]
  indexes=[i for a,b in windows for i in range(round(a*24),min(N,round(b*24)))]
  # Audio excerpts only in separate sample; full master uses the full unchanged reference stream.
  filt=';'.join(f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{j}]' for j,(a,b) in enumerate(windows))+';'+''.join(f'[a{j}]' for j in range(len(windows)))+f'concat=n={len(windows)}:v=0:a=1[out]'
  subprocess.run(['ffmpeg','-y','-v','error','-i',str(R/'revoice-swapped/audio.m4a'),'-filter_complex',filt,'-map','[out]','-c:a','aac','-b:a','192k',str(R/'revoice-swapped/sample-audio.m4a')],check=True)
  aud=R/'revoice-swapped/sample-audio.m4a';out=R/'revoice-swapped/sample.mp4';length=len(indexes)/24
 else:
  indexes=range(N);aud=R/'revoice-swapped/audio.m4a';out=R/'functional-podcast-revoice-swapped.mp4';length=D
 cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size','1280x720','-framerate','24','-i','-','-i',str(aud),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','25','-pix_fmt','yuv420p','-c:a','copy','-t',str(length),'-movflags','+faststart',str(out)]
 p=subprocess.Popen(cmd,stdin=subprocess.PIPE);started=time.monotonic()
 try:
  for done,i in enumerate(indexes):
   p.stdin.write(render(i).tobytes())
   if done%1440==0:
    stat={'frames':done,'total':len(indexes),'elapsed':round(time.monotonic()-started,1),'sample':sample}
    (R/'revoice-swapped/progress.json').write_text(json.dumps(stat));print(stat,flush=True)
  p.stdin.close();assert p.wait()==0
 except BaseException:p.kill();raise
 (R/'revoice-swapped/progress.json').write_text(json.dumps({'frames':len(indexes),'total':len(indexes),'status':'rendered','sample':sample}))
 print('COMPLETE',out,flush=True)
