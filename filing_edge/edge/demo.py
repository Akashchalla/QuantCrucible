"""Deterministic fabricated option paths for software demonstration, never market evidence."""
import math
import random
from datetime import date, timedelta
from .calendar import CAL, on_or_after, on_or_before, shift


def dataset(config):
    rng = random.Random(config['seed'])
    observations = []
    issuers = ['DEMO-A', 'DEMO-B', 'DEMO-C', 'DEMO-D', 'DEMO-E', 'DEMO-F', 'DEMO-G', 'DEMO-H']
    for i in range(48):
        anchor = shift(on_or_after('2024-04-01'), i*7)
        context = 'adverse' if i % 3 == 0 else 'standalone'
        ticker = issuers[i % len(issuers)]
        pair = f'synthetic-{i:03}'
        for role in ('event', 'control'):
            day = anchor if role == 'event' else shift(anchor, -35)
            available = shift(day, 1)
            obs = dict(id=pair+'-'+role, pair_id=pair, role=role, context=context,
                       ticker=ticker, anchor=day, available=available,
                       availability_basis='fabricated_next_session_availability',
                       source_url='', tags=['DEMO_BUYBACK']+(['DEMO_ADVERSE'] if context=='adverse' else []),
                       contracts=[])
            # Fabricated mechanisms deliberately include losses, missing marks and slow information decay.
            spot = 100+10*(i % 8)
            noise = rng.uniform(-0.003, 0.004)
            shock = 1.9 if i % 13 == 0 else 0
            for bucket, (lo, hi, target) in config['expiry_buckets'].items():
                expiry = on_or_before((date.fromisoformat(day)+timedelta(days=target)).isoformat())
                for otm in config['otm_grid']:
                    strike = round(spot*(1-otm), 2)
                    start_price = spot*(0.015+target/18000)*(1-otm*4)
                    bars = {}
                    start_i, end_i = CAL.index(shift(day, -22)), CAL.index(expiry)
                    max_n = max(1, end_i-CAL.index(day))
                    for j in range(start_i, end_i+1):
                        session = CAL[j]
                        n = j-CAL.index(day)
                        t = max(n, 0)
                        premium = start_price * max(0.05, 1-t/(max_n+5))
                        if role=='event' and n>=0:
                            premium *= (1-0.2*(1-math.exp(-t/12))) if context=='standalone' else (1+0.6*(1-math.exp(-t/12)))
                        premium += max(0, shock*(1-math.exp(-max(t-7,0)/8)))
                        premium *= max(0.7, 1+noise*t+0.04*math.sin(t*0.6+i))
                        if i % 17 == 0 and role=='event' and n==21:
                            continue
                        bars[session]={'close': round(max(0.02, premium), 4), 'volume': 1000+(i%9)*120}
                    obs['contracts'].append(dict(ticker=f'DEMO:{i}:{role}:{bucket}:{otm}', bucket=bucket,
                                                  otm=otm, strike=strike, expiry=expiry,
                                                  reference_spot=spot, bars=bars))
            observations.append(obs)
    return dict(schema_version=1, kind='synthetic', mode='development',
                event_start=config['development_start'], event_end=config['development_end'],
                outcome_cutoff=config['development_end'], observations=observations, drops=[],
                provenance={'source':'deterministic fabricated option-price paths', 'seed':config['seed'],
                            'warning':'SYNTHETIC DEMONSTRATION — NOT HISTORICAL RETURNS OR INVESTMENT EVIDENCE'})
