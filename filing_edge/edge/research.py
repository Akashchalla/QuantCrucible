"""Paired event-study accounting, explicit missingness and exploratory uncertainty."""
import math
import random
from collections import defaultdict, Counter
from statistics import mean, median
from .model import trade, validate_dataset
from .runtime import digest, now, require_freeze, save


def quantile(values, p):
    x = sorted(values)
    at = (len(x)-1)*p
    lo = int(at)
    return x[lo] + (x[min(lo+1,len(x)-1)]-x[lo])*(at-lo)


def cluster_interval(pairs, key, draws, seed):
    groups = defaultdict(list)
    for p in pairs:
        groups[key(p)].append(p['difference'])
    if len(groups) < 2:
        return None
    buckets, rng = list(groups.values()), random.Random(seed)
    simulated = []
    for _ in range(draws):
        values = [v for bucket in rng.choices(buckets,k=len(buckets)) for v in bucket]
        simulated.append(mean(values))
    return [quantile(simulated,.025), quantile(simulated,.975)]


def summarize(rows, draws, seed):
    by_pair = defaultdict(dict)
    for row in rows:
        if row['status'] == 'priced':
            by_pair[row['pair_id']][row['role']] = row
    pairs=[]
    for pair in by_pair.values():
        if set(pair) != {'event','control'}:
            continue
        e,c=pair['event'],pair['control']
        pairs.append(dict(ticker=e['ticker'], anchor=e['anchor'], event=e['net_return'],
                          control=c['net_return'], difference=e['net_return']-c['net_return']))
    n=len(pairs)
    if not n:
        return dict(pairs=0, issuers=0, edge=None, event_return=None, control_return=None,
                    interval=None, worst_event=None, status='insufficient data')
    issuer_ci=cluster_interval(pairs,lambda p:p['ticker'],draws,seed)
    calendar_ci=cluster_interval(pairs,lambda p:p['anchor'][:4]+'-Q'+str((int(p['anchor'][5:7])-1)//3+1),draws,seed+1)
    intervals=[x for x in [issuer_ci,calendar_ci] if x]
    ci=[min(x[0] for x in intervals),max(x[1] for x in intervals)] if len(intervals)==2 else None
    issuers=len(set(p['ticker'] for p in pairs))
    quarters=len(set((p['anchor'][:4],(int(p['anchor'][5:7])-1)//3) for p in pairs))
    return dict(pairs=n,issuers=issuers,calendar_clusters=quarters,
                edge=mean(p['difference'] for p in pairs),event_return=mean(p['event'] for p in pairs),
                control_return=mean(p['control'] for p in pairs),median_event=median(p['event'] for p in pairs),
                worst_event=min(p['event'] for p in pairs),interval=ci,issuer_interval=issuer_ci,
                calendar_interval=calendar_ci,status='exploratory' if n>=20 and issuers>=5 else 'small sample')


def evaluate(data,cfg):
    validate_dataset(data)
    if data['kind']=='massive':
        require_freeze(cfg)
    observations=data['observations']
    cutoff=data['outcome_cutoff']
    def price(horizon,delay,haircut,bucket=None,otm=None):
        return [trade(o,bucket or cfg['headline_bucket'], cfg['headline_otm'] if otm is None else otm,
                      horizon,delay,haircut,cfg['fee_per_contract_per_side'],cutoff) for o in observations]
    horizons=[]
    for h in cfg['horizons']:
        rows=price(h,cfg['headline_delay'],cfg['headline_haircut'])
        groups={ctx:summarize([r for r in rows if r['context']==ctx],cfg['bootstrap_draws'],cfg['seed'])
                for ctx in ('standalone','adverse')}
        horizons.append(dict(horizon=h,groups=groups,unavailable=dict(Counter(r['reason'] for r in rows if r['status']!='priced'))))
    grid=[]
    for delay in cfg['delays']:
        for haircut in cfg['haircuts']:
            rows=price(cfg['headline_horizon'],delay,haircut)
            s=summarize([r for r in rows if r['context']=='standalone'],cfg['bootstrap_draws'],cfg['seed'])
            grid.append(dict(delay=delay,haircut=haircut,**s))
    sensitivity=[]
    for bucket in cfg['expiry_buckets']:
        for otm in cfg['otm_grid']:
            rows=price(cfg['headline_horizon'],cfg['headline_delay'],cfg['headline_haircut'],bucket,otm)
            sensitivity.append(dict(bucket=bucket,otm=otm,**summarize([r for r in rows if r['context']=='standalone'],cfg['bootstrap_draws'],cfg['seed'])))
    headline_rows=price(cfg['headline_horizon'],cfg['headline_delay'],cfg['headline_haircut'])
    representatives=[r for r in headline_rows if r['status']=='priced' and r['role']=='event']
    stamp=now()
    report=dict(schema_version=1,kind=data['kind'],mode=data['mode'],created_at=stamp,
                run_id=digest({'data':digest(data),'config':digest(cfg),'at':stamp})[:20],
                config_hash=digest(cfg),data_hash=digest(data),config=cfg,
                observations=len(observations),event_count=sum(o['role']=='event' for o in observations),
                horizons=horizons,grid=grid,sensitivity=sensitivity,trades=representatives,
                drops=data.get('drops',[]),provenance=data.get('provenance',{}),
                outcome_cutoff=cutoff,
                warnings=[
                    'SYNTHETIC DEMONSTRATION — not historical evidence.' if data['kind']=='synthetic' else 'Historical daily-trade-price simulation, not verified executable fills.',
                    'Intervals are exploratory envelopes of issuer and calendar-quarter cluster bootstraps. Cross-quarter overlap and small cluster counts remain limitations.',
                    'Each cell uses complete event-control pairs; sample composition may change with parameters.',
                    'Event-study returns are on full strike collateral. They are not a funded portfolio, CAGR or portfolio Sharpe.',
                    'Expiry is a last-trade-price proxy; assignment and settlement are not fully modeled.',
                    'Cash interest is excluded on both sides. Daily closes do not establish bid/ask spreads.'])
    save('report-'+data['kind']+'.json',report)
    return report


def capital(account,spot,strike,premium,allocation,fee=.65):
    values=[account,spot,strike,premium,allocation,fee]
    if any(not math.isfinite(v) for v in values) or min(account,spot,strike)<=0 or premium<0 or premium>=strike or fee<0 or not 0<allocation<=1:
        raise ValueError('Enter finite positive account/price values and a valid allocation.')
    contracts=math.floor((account*allocation)/(100*strike+fee))
    collateral=contracts*100*strike
    scenarios=[]
    for change in [-1,-.5,-.3,-.2,-.1,-.05,0,.1,.2]:
        terminal=spot*(1+change)
        pnl=contracts*(100*(premium-max(strike-terminal,0))-fee)
        scenarios.append(dict(move=change,terminal=terminal,pnl=pnl,account_return=pnl/account))
    return dict(contracts=contracts,collateral=collateral,unused_cash=account-collateral-contracts*fee,
                premium_received=contracts*100*premium,breakeven=strike-premium+fee/100,
                max_loss=contracts*(100*(strike-premium)+fee),scenarios=scenarios,
                note='Hypothetical expiry payoffs, entry fee only; excludes early assignment, taxes and financing. No probabilities are assigned.')
