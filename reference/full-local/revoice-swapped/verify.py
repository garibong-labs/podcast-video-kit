from pathlib import Path
import json,subprocess,hashlib,wave,sys,numpy as np
from PIL import Image,ImageDraw
R=Path(__file__).resolve().parent;B=R.parent
sample='--sample' in sys.argv
v=R/'sample.mp4' if sample else B/'functional-podcast-revoice-swapped.mp4'
p=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(v)]))
vs=next(s for s in p['streams'] if s['codec_type']=='video');au=next(s for s in p['streams'] if s['codec_type']=='audio')
assert (vs['width'],vs['height'])==(1280,720)
subprocess.run(['ffmpeg','-v','error','-i',str(v),'-f','null','-'],check=True)
if sample:
 times=[2,12,16,22,26,31,36,42,47];sheet=Image.new('RGB',(960,540))
else:
 times=[1,12,27,58.98,244,260,334,360,710,745,930,1030,1230,1400,1768,1790];sheet=Image.new('RGB',(1280,720))
for i,t in enumerate(times):
 f=R/('sample' if sample else 'encoded')/f'{i:02}.jpg';f.parent.mkdir(exist_ok=True)
 subprocess.run(['ffmpeg','-y','-v','error','-ss',str(t),'-i',str(v),'-frames:v','1',str(f)],check=True)
 im=Image.open(f).resize((320,180));ImageDraw.Draw(im).text((4,4),f'{t:.2f}s',fill='white',stroke_fill='black',stroke_width=1)
 cols=3 if sample else 4;sheet.paste(im,((i%cols)*320,(i//cols)*180))
sheet.save(R/('sample-contact.jpg' if sample else 'encoded-contact.jpg'),quality=94)
result={'decode':'PASS','duration':float(p['format']['duration']),'video_frames':int(vs['nb_read_frames']),'audio_duration':float(au['duration']),'bytes':v.stat().st_size,'visual_review':'pending','listening_review':'not performed','caption_method':'local Whisper word timestamps; automatic transcript, not fully human proofread','speaker_method':'monotonic script matching; not acoustic diarization'}
if not sample:
 T=json.loads((R/'timeline.json').read_text())['turns'];C=json.loads((R/'captions.json').read_text())
 assert len(T)==89 and set(c['turn'] for c in C)==set(range(89))
 assert result['video_frames']==42993
 assert abs(result['duration']-1791.36)<.06
 src=next(B.parent.glob('Generated*.wav'))
 with wave.open(str(src),'rb') as w:
  dur=w.getnframes()/w.getframerate();result['source_format']={'rate':w.getframerate(),'channels':w.getnchannels(),'width':w.getsampwidth(),'frames':w.getnframes(),'duration':dur}
 assert abs(result['audio_duration']-dur)<.04
 def ah(path):return hashlib.sha256(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-c:a','copy','-f','adts','-'])).hexdigest()
 assert ah(v)==ah(R/'audio.m4a');result['AAC_reference_identity']='PASS: full uncut source encoded once then copied'
 states=np.load(R/'revoice-mouth-states.npy')
 with wave.open(str(R/'analysis.wav'),'rb') as w:pcm=w.readframes(w.getnframes())
 x=np.frombuffer(pcm,dtype='<i2').astype(float)/32768;x=np.pad(x,(0,len(states)*1000-len(x)))
 rms=np.sqrt(np.mean(x.reshape(-1,1000)**2,axis=1));assert np.all(states[rms<.006]==0)
 result['quiet_mouth_closed']='PASS';result['turns']=89;result['captions']=len(C)
 scenes=json.loads((R/'scenes.json').read_text());assert all(a['end']<=b['start'] for a,b in zip(scenes,scenes[1:]));result['concept_intervals']=len(scenes)
 result['sha256']=hashlib.sha256(v.read_bytes()).hexdigest();result['source_wav_sha256']=hashlib.sha256(src.read_bytes()).hexdigest()
(R/('sample-verification.json' if sample else 'verification.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
