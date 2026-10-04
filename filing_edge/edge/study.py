"""Versioned, date-parameterized quote research. Outcome access is recorded before collection."""
import json, math, statistics, hashlib
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import date
from .runtime import ROOT, read, save, config, digest, now
from .collect import contracts, reference_spot, price_observation
from .calendar import CAL, shift, on_or_before
from .providers import Massive
from .model import contract_for
from .execution import quote, open_short, close_short
from .research import summarize

# Reuse the audited filing extraction with a separate destination and arbitrary authorized window.
from .calendar import on_or_after
from .providers import ProviderError
def coverage_window(cfg,progress=lambda _:None):
    m=Massive(600)
    start,end=cfg['development_start'],cfg['development_end']
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
    save('coverage-v2-'+start+'-'+end+'.json',result)
    return result


def protocol():
    return json.loads((ROOT/'protocol-v2.json').read_text())


def fingerprint():
    names=['study.py','execution.py','portfolio.py','collect.py','calendar.py','model.py','research.py','providers.py','runtime.py']
    return digest({n:(ROOT/'edge'/n).read_text() for n in names}|{'config':config(),'protocol':protocol()})


def freeze_v2():
    record=dict(created_at=now(),source_hash=fingerprint(),config=config(),protocol=protocol(),
        disclosure='Version 1 development results were already inspected. Version 2 is a disclosed revision, frozen before accessing the 2026 test returns.')
    old=read('freeze-v2.json')
    if old and old['source_hash']!=record['source_hash']:
        raise ValueError('Frozen v2 research changed. Preserve it and explicitly version the new method.')
    if not old:save('freeze-v2.json',record)
    return old or record


def quoted_trade(obs,bucket,otm,horizon,delay,haircut,fee,cutoff):
    row={k:obs[k] for k in ('id','pair_id','role','context','ticker','anchor','available')}
    row.update(status='unavailable',reason='',horizon=horizon,delay=delay,haircut=haircut)
    c=contract_for(obs,bucket,otm)
    if not c:return dict(row,reason='no_eligible_contract')
    entry=shift(obs['anchor'],delay)
    exit_day=on_or_before(c['expiry']) if horizon=='exp' else shift(obs['anchor'],horizon)
    row.update(entry=entry,exit=exit_day,contract=c['ticker'],strike=c['strike'],expiry=c['expiry'])
    if entry<obs['available']:return dict(row,reason='signal_not_available')
    if exit_day<=entry:return dict(row,reason='horizon_not_after_entry')
    if exit_day>on_or_before(c['expiry']):return dict(row,reason='expired_before_horizon')
    if exit_day>cutoff:return dict(row,reason='outcome_beyond_window')
    e=c.get('quotes',{}).get(entry,{})
    x=c.get('quotes',{}).get(exit_day,{})
    if e.get('status')!='usable':return dict(row,reason='entry_'+e.get('reason','missing_quote'))
    if x.get('status')!='usable':return dict(row,reason='exit_'+x.get('reason','missing_quote'))
    cash_in=open_short(e,1,fee,haircut);cash_out=close_short(x,1,fee,haircut)
    collateral=100*c['strike']
    return dict(row,status='priced',entry_mark=e['bid'],exit_mark=x['ask'],collateral=collateral,
        net_pnl=cash_in-cash_out,net_return=(cash_in-cash_out)/collateral,
        gross_pnl=100*(e['bid']-x['ask']),costs=100*haircut*(e['bid']+x['ask'])+2*fee,
        entry_quote=e,exit_quote=x,exit_basis='preclose_NBBO_buyback_proxy',
        reference_spot=c['reference_spot'],source_url=obs.get('source_url',''))


def risk_feature(obs,cfg):
    c=contract_for(obs,cfg['headline_bucket'],cfg['headline_otm'])
    if not c:return None
    day=shift(obs['anchor'],-1);b=c['bars'].get(day)
    if not b or b['close']<=0:return None
    return dict(premium_fraction=b['close']/c['strike'],dte=(date.fromisoformat(c['expiry'])-date.fromisoformat(day)).days,
                otm=1-c['strike']/c['reference_spot'])


def enrich(obs,cfg,p,cutoff):
    m=Massive(2500)
    for c in obs['contracts']:
        days={shift(obs['anchor'],n) for n in set(cfg['delays']+[h for h in cfg['horizons'] if h!='exp'])}
        days.add(on_or_before(c['expiry']))
        if obs['role']=='event' and c['bucket']==cfg['headline_bucket'] and c['otm']==cfg['headline_otm']:
            days.update(d for d in CAL if shift(obs['anchor'],1)<=d<=min(cutoff,on_or_before(c['expiry'])))
        c['quotes']={day:quote(m,c['ticker'],day,p) for day in sorted(days) if day<=cutoff and day<=on_or_before(c['expiry'])}
    return obs


def evaluate(data,cfg,p):
    def rows(h,d,c,b=None,o=None):
        return [quoted_trade(x,b or cfg['headline_bucket'],cfg['headline_otm'] if o is None else o,h,d,c,
                            cfg['fee_per_contract_per_side'],data['outcome_cutoff']) for x in data['observations']]
    def summary(r):return summarize(r,p['bootstrap_draws'],cfg['seed'])
    horizons=[]
    for h in cfg['horizons']:
        rr=rows(h,cfg['headline_delay'],cfg['headline_haircut'])
        horizons.append(dict(horizon=h,groups={ctx:summary([x for x in rr if x['context']==ctx]) for ctx in ('standalone','adverse')},
            unavailable=dict(Counter(x['reason'] for x in rr if x['status']!='priced'))))
    grid=[dict(delay=d,haircut=c,**summary([r for r in rows(cfg['headline_horizon'],d,c) if r['context']=='standalone'])) for d in cfg['delays'] for c in cfg['haircuts']]
    sensitivity=[dict(bucket=b,otm=o,**summary([r for r in rows(cfg['headline_horizon'],cfg['headline_delay'],cfg['headline_haircut'],b,o) if r['context']=='standalone'])) for b in cfg['expiry_buckets'] for o in cfg['otm_grid']]
    rr=rows(cfg['headline_horizon'],cfg['headline_delay'],cfg['headline_haircut'])
    from .portfolio import simulate
    return dict(schema_version=2,kind='massive',mode=data['mode'],created_at=now(),run_id=digest(data)[:20],data_hash=digest(data),
        config=cfg,protocol=p,config_hash=digest({'config':cfg,'protocol':p}),start=data['event_start'],end=data['event_end'],
        outcome_cutoff=data['outcome_cutoff'],event_count=data['event_count'],observations=len(data['observations']),
        horizons=horizons,grid=grid,sensitivity=sensitivity,trades=[r for r in rr if r['role']=='event' and r['status']=='priced'],
        drops=data['drops'],provenance=data['provenance'],portfolio=simulate(data,cfg,p),
        decision='RESEARCH ONLY — LIVE TRADING NOT APPROVED',
        warnings=['NBBO snapshots are indicative, not guaranteed fills; prices include adverse haircuts and per-contract fees.',
        'Classification availability was not archived at the historical decision time. A one-session delay is an assumption.',
        'Fixed 2026 issuer universe creates selection/survivorship risk. Parity uses American daily closes, a fixed rate and no dividends.',
        'Controls match pre-anchor premium/strike and maturity, not all risk factors; the study is observational, not causal.',
        'Uncertainty is an exploratory envelope of issuer and quarter bootstrap intervals, not joint two-way cluster inference.',
        'Every result cell uses complete pairs; missing quotes can bias the sample. Expiry is a preclose buyback, not settlement.',
        'Early assignment is stress-tested, not reconstructed from historical exercise notices. No live trading or broker connection.'])


def run_window(start,end,mode='sealed',progress=print):
    date.fromisoformat(start);date.fromisoformat(end)
    if not '2022-03-01'<=start<=end<=config()['data_cutoff']:raise ValueError('Window must be within supported historical coverage, from March 2022 through the configured cutoff.')
    if mode not in ('development','test','sealed'):raise ValueError('Unknown study mode.')
    if mode=='development' and (start,end)!=('2024-01-01','2025-12-31'):raise ValueError('Development dates are fixed.')
    if mode=='test' and (start,end)!=('2026-01-01','2026-08-31'):raise ValueError('Test dates are fixed.')
    frozen=freeze_v2();key=f'{mode}-{start}-{end}';name='report-v2-'+key+'.json'
    old=read(name)
    if old:return old
    access=read('access-v2-'+key+'.json')
    if access and access['source_hash']!=frozen['source_hash']:raise ValueError('An accessed window cannot be rerun under changed research code.')
    if not access:save('access-v2-'+key+'.json',dict(start=start,end=end,mode=mode,source_hash=frozen['source_hash'],first_access=now()))
    cfg=config();cfg.update(development_start=start,development_end=end)
    p=protocol();data=read('dataset-v2-'+key+'.json')
    if not data:
        cov=coverage_window(cfg,progress);events=cov['events'];obs=[];drops=[]
        if len(events)>p['max_events']:raise ValueError('Event safety limit reached. Refusing silent truncation.')
        # Each worker owns its request budget. Decisions use pre-anchor data; outcomes are not consulted for matching.
        def collect_event(e):
            m=Massive(3500);event,reason=price_observation(m,e,e['anchor'],'event',cfg,end)
            feature=risk_feature(event,cfg);candidates=[]
            if feature:
                for lag in cfg['control_lags']:
                    anchor=shift(e['anchor'],-lag)
                    if anchor<start:continue
                    if any(x['ticker']==e['ticker'] and abs(CAL.index(x['anchor'])-CAL.index(anchor))<=cfg['control_exclusion_sessions'] for x in events):continue
                    control,_=price_observation(m,e,anchor,'control',cfg,end);f=risk_feature(control,cfg)
                    if not f:continue
                    ratio=max(f['premium_fraction'],feature['premium_fraction'])/min(f['premium_fraction'],feature['premium_fraction'])
                    if ratio<=p['maximum_risk_ratio'] and abs(f['dte']-feature['dte'])<=p['maximum_dte_difference']:
                        candidates.append((abs(math.log(ratio))+abs(f['dte']-feature['dte'])/365,anchor,control))
            chosen=min(candidates,key=lambda x:(x[0],x[1]))[2] if candidates else None
            event['matched']=chosen is not None
            # Keep unmatched events in the funded simulation; paired statistics require both roles.
            return [event]+([chosen] if chosen else []),dict(id=e['id'],reason=reason or ('no_preentry_risk_matched_control' if not chosen else ''))
        with ThreadPoolExecutor(max_workers=p['network_workers']) as pool:
            for i,(items,drop) in enumerate(pool.map(collect_event,events)):
                obs.extend(items)
                if drop['reason']:drops.append(drop)
                progress(f'Collected event {i+1}/{len(events)}; quote audit follows')
        # Checkpoint before quote work so an interrupted request resumes cached price collection.
        data=dict(schema_version=2,mode=mode,kind='massive',event_start=start,event_end=end,outcome_cutoff=end,event_count=len(events),observations=obs,drops=drops,
            provenance=dict(source='Massive filings, option contracts, daily option trades and historical NBBO',created_at=now(),freeze_hash=frozen['source_hash'],partial_sample=False,
            control='Same issuer: closest pre-anchor premium/strike and maturity among fixed backward offsets; no return-based matching.',
            timing='Historical tag timing unverified; one-session assumed delay. Outcomes truncated at window end.'))
        save('dataset-v2-'+key+'.json',data)
    with ThreadPoolExecutor(max_workers=p['network_workers']) as pool:
        enriched=[]
        for i,item in enumerate(pool.map(lambda o:enrich(o,cfg,p,end),data['observations'])):
            enriched.append(item);progress(f'Quote audit {i+1}/{len(data["observations"])}')
    data['observations']=enriched;save('dataset-v2-'+key+'.json',data)
    report=evaluate(data,cfg,p);save(name,report);save('report-v2-latest.json',report)
    return report
