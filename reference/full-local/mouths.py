from pathlib import Path
from PIL import Image,ImageDraw
import json,numpy as np
R=Path(__file__).resolve().parent;P=R.parent
NAMES=['wide','A_close','B_threequarter','over_A','over_B','high']
LANDMARKS=json.loads((R/'mouth-landmarks-640.json').read_text())
# Texture deformation uses existing lips and skin; no external model or generated mouth.
def warp_patch(im,point,state,name):
 x,y,w=point;x*=2;y*=2;w*=2
 if name=='high':x+=4;y+=3
 radiusx=int(w*.95+12);radiusy=int(w*.75+12)
 box=(int(x-radiusx),int(y-radiusy),int(x+radiusx+1),int(y+radiusy+1))
 patch=im.crop(box);a=np.asarray(patch).astype(np.float32);hh,ww=a.shape[:2]
 yy,xx=np.mgrid[:hh,:ww].astype(np.float32);dy=yy-radiusy;dx=xx-radiusx
 base=5.0 if name=='B_threequarter' else 2.7
 target=(1.4 if name=='B_threequarter' else base) if state==0 else base+state*1.35
 if name=='high':target=base+state*.8
 weight=np.exp(-(dx/(w*.57))**6)
 local=base+(target-base)*weight
 ad=np.abs(dy)
 sy=np.where(ad<=local,ad*base/local,base+(ad-local)*(radiusy-base)/(radiusy-local))
 sy=np.clip(radiusy+np.sign(dy)*sy,0,hh-1)
 # Slight change in mouth width during opening, not unrelated rhythmic motion.
 sx=np.clip(radiusx+dx*(1+state*.005*np.exp(-(dy/(radiusy*.55))**4)),0,ww-1)
 x0=np.floor(sx).astype(int);y0=np.floor(sy).astype(int);x1=np.minimum(x0+1,ww-1);y1=np.minimum(y0+1,hh-1)
 wx=(sx-x0)[...,None];wy=(sy-y0)[...,None]
 rgb=(a[y0,x0]*(1-wx)*(1-wy)+a[y0,x1]*wx*(1-wy)+a[y1,x0]*(1-wx)*wy+a[y1,x1]*wx*wy)
 result=Image.fromarray(np.uint8(np.clip(rgb,0,255)))
 if state>0 and name!='B_threequarter':
  # Existing closed lip texture alone would merely stretch. Add a small inner cavity.
  high=result.resize((ww*3,hh*3),Image.Resampling.BICUBIC);d=ImageDraw.Draw(high)
  cx=radiusx*3;cy=(radiusy+1)*3;rx=w*.35*3;ry=(1.2+state*.96)*3
  d.ellipse((cx-rx,cy-ry,cx+rx,cy+ry),fill='#39201c',outline='#563027',width=2)
  if state>=3:d.ellipse((cx-rx*.62,cy+ry*.40,cx+rx*.62,cy+ry*.82),fill='#9a5a4a')
  result=high.resize((ww,hh),Image.Resampling.LANCZOS)
 return result,box[:2]
BASES={};POSES={}
for name in NAMES:
 im=Image.open(P/'multiangle'/(name+'.jpg')).convert('RGB');im=im.resize((1280,round(im.height*1280/im.width)),Image.Resampling.LANCZOS)
 BASES[name]=im;POSES[name]={}
 for speaker,point in LANDMARKS[name].items():POSES[name][speaker]=[warp_patch(im,point,state,name) for state in range(8)]
def portrait(name,speaker=None,state=0):
 im=BASES[name].copy()
 for who,poses in POSES[name].items():
  patch,pos=poses[state if who==speaker else 0];im.paste(patch,pos)
 return im
if __name__=='__main__':
 sheet=Image.new('RGB',(960,720),'#eee')
 for j,(name,who) in enumerate([('A_close','A'),('B_threequarter','B'),('wide','A'),('wide','B')]):
  for k,state in enumerate([0,3,7]):
   im=portrait(name,who,state);x,y,w=LANDMARKS[name][who];crop=im.crop((x*2-90,y*2-70,x*2+90,y*2+70)).resize((240,180))
   sheet.paste(crop,(k*320,j*180))
 sheet.save(R/'mouth-poses.jpg',quality=94)
 print('POSES',sum(len(p) for n in POSES.values() for p in n.values()))
