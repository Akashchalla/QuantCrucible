"""Development-only coverage and bounded historical option collection."""
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import math
import statistics
from .providers import Massive, ProviderError
from .runtime import save, read, now, digest, require_freeze
from .calendar import CAL, on_or_after, on_or_before, shift


def coverage(cfg,progress=lambda _:None):
    m=Massive(600)
    start,end=cfg['development_start'],cfg['development_end']
    if not ('2024-01-01'<=start<=end<='2025-12-31'):
        raise ValueError('Dashboard collection is restricted to the development window.')
    tags=cfg['buyback_tags']
    if not tags:
        raise ValueError('Set verified buyback taxonomy tags in config.json before collection.')
    raw=[]
    for tag in tags:
        progress('Collecting development filings: '+tag)
        raw.extend(m.rows('/stocks/filings/8-K/vX/disclosures',{'tertiary_category':tag,'filing_date.gte':start,'filing_date.lte':end,'limit':1000,'sort':'filing_date.asc'}))
    chosen={}
    for r in raw:
        candidates=sorted({t.replace('/','.').upper() for t in r.get('tickers',[]) if isinstance(t,str)} & set(cfg['universe']))
        if candidates:
            key=r.get('accession_number')
            if not key:
                continue
            chosen.setdefault(key,{**r,'ticker':candidates[0]})
    events=[]
    for i,(accession,r) in enumerate(sorted(chosen.items(),key=lambda kv:(kv[1]['filing_date'],kv[0]))):
        progress(f'Reading co-disclosures {i+1}/{len(chosen)}')
        # Query by ticker/date, then join only the exact accession. A filing may have many event rows.
        siblings=m.rows('/stocks/filings/8-K/vX/disclosures',{'tickers':r['ticker'],'filing_date':r['filing_date'],'limit':1000})
        siblings=[s for s in siblings if s.get('accession_number')==accession]
        if not siblings:
            raise ProviderError('Co-disclosure query returned no matching filing; refusing to infer absence of adverse tags.')
        seen=set(); disclosures=[]
        for s in siblings:
            identity=(s.get('tertiary_category',''),s.get('supporting_text',''))
            if identity not in seen:
                disclosures.append({'category':identity[0],'text':identity[1]})
                seen.add(identity)
        categories=sorted({d['category'] for d in disclosures})
        anchor=on_or_after(r['filing_date'])
        available=shift(anchor,cfg['assumed_tag_delay_sessions'])
        events.append(dict(id=accession,ticker=r['ticker'],filing_date=r['filing_date'],anchor=anchor,
                           available=available,context='adverse' if set(categories)&set(cfg['adverse_tags']) else 'standalone',
                           tags=categories,disclosures=disclosures,source_url=r.get('filing_url',''),
                           availability_basis='assumed_next_session_tag_load; historical availability unverified'))
    result=dict(created_at=now(),kind='massive',mode='development',start=start,end=end,
                config_hash=digest(cfg),events=events,filings=len(events),issuers=len({e['ticker'] for e in events}),
                context_counts=dict(Counter(e['context'] for e in events)),
                note='Coverage only. No returns evaluated. Labels may be retrospective; absence of an adverse tag is not absence of adverse information.')
    save('coverage.json',result)
    return result


def bars(m,ticker,start,end):
    if start>end:return {}
    rows=m.rows(f'/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}',{'adjusted':'false','sort':'asc','limit':50000})
    out={}
    for r in rows:
        day=datetime.fromtimestamp(r['t']/1000,ZoneInfo('America/New_York')).date().isoformat()
        if start<=day<=end:
            out[day]={'close':float(r['c']),'volume':float(r.get('v',0))}
    return out


def contracts(m,ticker,reference):
    dt=date.fromisoformat(reference)
    raw=m.rows('/v3/reference/options/contracts',{
        'underlying_ticker':ticker,'as_of':reference,'expired':'false',
        'expiration_date.gte':(dt+timedelta(days=3)).isoformat(),
        'expiration_date.lte':(dt+timedelta(days=180)).isoformat(),'limit':1000})
    return [c for c in raw if c.get('shares_per_contract')==100 and not c.get('additional_underlyings')
            and c.get('contract_type') in ('put','call') and c.get('strike_price',0)>0]


def reference_spot(m,chain,reference,rate):
    by_expiry=defaultdict(lambda:defaultdict(dict))
    for c in chain:by_expiry[c['expiration_date']][c['strike_price']][c['contract_type']]=c
    for expiry,strikes in sorted(by_expiry.items())[:3]:
        pairs={k:v for k,v in strikes.items() if set(v)=={'call','put'}}
        if len(pairs)<3:continue
        guess=statistics.median(pairs)
        tried=set()
        for _ in range(6):
            remaining=[k for k in pairs if k not in tried]
            if not remaining:break
            k=min(remaining,key=lambda k:abs(k-guess));tried.add(k)
            c=bars(m,pairs[k]['call']['ticker'],reference,reference).get(reference)
            p=bars(m,pairs[k]['put']['ticker'],reference,reference).get(reference)
            if not c or not p or min(c['volume'],p['volume'])<=0:continue
            estimate=k*math.exp(-rate*(date.fromisoformat(expiry)-date.fromisoformat(reference)).days/365)+c['close']-p['close']
            if estimate<=0:continue
            if abs(k-estimate)/estimate<.08:
                return estimate
            guess=estimate
    return None


def price_observation(m,event,anchor,role,cfg,cutoff):
    reference=shift(anchor,-1)
    chain=contracts(m,event['ticker'],reference)
    spot=reference_spot(m,chain,reference,cfg['parity_rate']) if chain else None
    obs=dict(id=event['id']+'-'+role,pair_id=event['id'],role=role,context=event['context'],ticker=event['ticker'],
             anchor=anchor,available=shift(anchor,cfg['assumed_tag_delay_sessions']),
             availability_basis=event['availability_basis'],source_url=event['source_url'] if role=='event' else '',
             tags=event['tags'] if role=='event' else [],contracts=[])
    if spot is None:return obs,'no_fresh_parity_reference'
    for bucket,(lo,hi,target) in cfg['expiry_buckets'].items():
        eligible=[c for c in chain if c['contract_type']=='put' and lo <= (date.fromisoformat(c['expiration_date'])-date.fromisoformat(reference)).days <=hi]
        expiries=sorted({c['expiration_date'] for c in eligible})
        if not expiries:continue
        expiry=min(expiries,key=lambda d:(abs((date.fromisoformat(d)-date.fromisoformat(reference)).days-target),d))
        for otm in cfg['otm_grid']:
            options=[c for c in eligible if c['expiration_date']==expiry and .5*spot <= c['strike_price']<=spot*(1-otm)]
            if not options:continue
            c=max(options,key=lambda c:c['strike_price'])
            series=bars(m,c['ticker'],shift(anchor,-22),min(expiry,cutoff))
            obs['contracts'].append(dict(ticker=c['ticker'],bucket=bucket,otm=otm,strike=c['strike_price'],
                                         expiry=expiry,reference_spot=spot,bars=series))
    return obs,'' if obs['contracts'] else 'no_eligible_put_contracts'


def collect(cfg,limit=12,progress=lambda _:None):
    require_freeze(cfg)
    cov=read('coverage.json')
    if not cov or cov['config_hash']!=digest(cfg):raise ValueError('Run coverage with the current configuration first.')
    m=Massive(1800)
    events=cov['events']
    cutoff=cfg['development_end']; observations=[];drops=[]
    # Deterministic selection, not outcome selection. Limit is disclosed in provenance.
    for i,e in enumerate(events[:limit]):
        progress(f'Pricing development pair {i+1}/{min(limit,len(events))}: {e["ticker"]}')
        controls=[]
        for lag in cfg['control_lags']:
            candidate=shift(e['anchor'],-lag)
            if candidate<cfg['development_start']:continue
            if any(x['ticker']==e['ticker'] and abs(CAL.index(x['anchor'])-CAL.index(candidate))<=cfg['control_exclusion_sessions'] for x in events):continue
            controls.append(candidate)
        if not controls:
            drops.append(dict(id=e['id'],reason='no_matched_control_date'));continue
        for role,anchor in [('event',e['anchor']),('control',controls[0])]:
            obs,reason=price_observation(m,e,anchor,role,cfg,cutoff)
            observations.append(obs)
            if reason:drops.append(dict(id=obs['id'],reason=reason))
    dataset=dict(schema_version=1,kind='massive',mode='development',outcome_cutoff=cutoff,
        event_start=cfg['development_start'],event_end=cfg['development_end'],observations=observations,drops=drops,
        provenance=dict(source='Massive REST API',created_at=now(),total_coverage_events=len(events),requested_limit=limit,
            partial_sample=limit<len(events),reference='Pre-filing European parity approximation from fresh American option daily trades; dividends and asynchronous prices can bias it.',
            control='Same issuer, first eligible prespecified backward session offset. Nearby buyback exclusion is a retrospective research control, not a trading rule. Risk matching is not implemented.',
            warning='Pilot observational study; ordinary-day risk matching, assignment lifecycle and executable quote verification remain incomplete.'))
    save('dataset-massive.json',dataset)
    return dataset
