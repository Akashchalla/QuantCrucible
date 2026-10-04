"""Report-grounded ElevenLabs narration with a visible, deterministic transcript."""
import json,os,re,tempfile
from urllib.request import Request,build_opener
from urllib.error import HTTPError,URLError
from .providers import ProviderError,NoRedirect
from .runtime import read,save,settings,PRIVATE,digest,now


def transcript(report):
    h=next(x for x in report['horizons'] if x['horizon']==21)['groups']['standalone']
    scope=report.get('mode','development')
    text=f'This is an AI generated Filing Edge research briefing. This report covers the {scope} window. We asked whether selling cash secured put options after a share repurchase disclosure performed differently from ordinary days for the same company. '
    if h['edge'] is None:
        text+='No complete, usable event and control pairs survived the primary comparison. We cannot estimate an edge from this sample. '
    else:
        text+=f'The primary comparison has {h["pairs"]} complete pairs across {h["issuers"]} companies. The average difference is {h["edge"]*10000:.1f} basis points of reserved collateral. '
        if h.get('interval'):
            lo,hi=h['interval'];text+=f'The exploratory uncertainty interval runs from {lo*10000:.1f} to {hi*10000:.1f} basis points. '
            if lo<=0<=hi:text+='That interval includes zero, so these results do not establish a positive edge. '
    if h.get('pairs',0)<20:
        text+='This is a small sample, so the estimated difference is fragile. '
    if h.get('event_return') is not None and h['event_return']<0:
        text+='The event trades themselves lost money on average; relative outperformance is not absolute profit. '
    pf=report.get('portfolio')
    if pf:text+=f'The capital constrained simulation admitted {pf["trade_count"]} position or positions. Its total account return was {pf["total_return"]*100:.2f} percent. Missing price marks received a conservative full liability reserve on {pf["stale_mark_days"]} days. '
    text+='The decision is research only. Historical classification availability and early assignment are not fully verified. An attractive average is not permission to trade. Every assumption, missing observation and cost is retained for review.'
    return text


def generate(report):
    text=transcript(report);env=settings();voice=env.get('ELEVENLABS_VOICE_ID','EXAVITQu4vr4xnSDxMaL');model=env.get('ELEVENLABS_TTS_MODEL','eleven_v4')
    if not re.fullmatch('[A-Za-z0-9_-]{1,80}',voice):raise ProviderError('Invalid voice identifier.')
    key=digest({'text':text,'voice':voice,'model':model})
    existing=read('audio-'+key+'.json')
    if existing and (PRIVATE/('audio-'+key+'.mp3')).exists():return existing
    if not env.get('ELEVENLABS_API_KEY'):raise ProviderError('Configure ELEVENLABS_API_KEY locally.')
    body=json.dumps({'text':text,'model_id':model}).encode()
    req=Request(f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128',data=body,
        headers={'xi-api-key':env['ELEVENLABS_API_KEY'],'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect()).open(req,timeout=60) as response:
            audio=response.read(12_000_001)
            if len(audio)>12_000_000 or len(audio)<1000:raise ProviderError('Invalid audio response size.')
    except HTTPError as exc:raise ProviderError(f'ElevenLabs HTTP {exc.code}; narration was not generated.') from None
    except (OSError,URLError):raise ProviderError('ElevenLabs connection failed.') from None
    PRIVATE.mkdir(exist_ok=True,mode=0o700);fd,temp=tempfile.mkstemp(dir=PRIVATE)
    with os.fdopen(fd,'wb') as f:f.write(audio)
    os.replace(temp,PRIVATE/('audio-'+key+'.mp3'))
    result=dict(id=key,url='/api/audio/'+key,transcript=text,generated_at=now(),provider='ElevenLabs',voice=voice,ai_generated=True,run_id=report['run_id'])
    save('audio-'+key+'.json',result);save('audio-latest.json',result)
    return result
