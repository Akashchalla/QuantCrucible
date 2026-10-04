"""Pure research accounting. Every observation has an explicit availability date."""
from datetime import date
import math
from .calendar import on_or_before, shift


def contract_for(obs, bucket, otm):
    return next((c for c in obs['contracts'] if c['bucket'] == bucket and abs(c['otm']-otm) < 1e-8), None)


def fresh_bar(contract, day):
    bar = contract['bars'].get(day)
    if not bar or not math.isfinite(bar['close']) or bar['close'] <= 0 or not math.isfinite(bar['volume']) or bar['volume'] <= 0:
        return None
    return bar


def trade(obs, bucket, otm, horizon, delay, haircut, fee, cutoff):
    if not isinstance(delay, int) or delay < 0 or not math.isfinite(haircut) or not 0 <= haircut < 1 or not math.isfinite(fee) or fee < 0:
        raise ValueError('Invalid execution assumptions.')
    row = {k: obs[k] for k in ('id', 'pair_id', 'role', 'context', 'ticker', 'anchor', 'available')}
    row.update(bucket=bucket, otm=otm, horizon=horizon, delay=delay, haircut=haircut,
               status='unavailable', reason='', source_url=obs.get('source_url', ''),
               tags=obs.get('tags', []), availability_basis=obs.get('availability_basis', 'unspecified'))
    c = contract_for(obs, bucket, otm)
    if c is None:
        return dict(row, reason='no_eligible_contract')
    entry = shift(obs['anchor'], delay)
    expiry = on_or_before(c['expiry'])
    exit_day = expiry if horizon == 'exp' else shift(obs['anchor'], int(horizon))
    row.update(entry=entry, exit=exit_day, contract=c['ticker'], strike=c['strike'], expiry=c['expiry'])
    if entry < obs['available']:
        return dict(row, reason='signal_not_available')
    if exit_day <= entry:
        return dict(row, reason='horizon_not_after_eligible_entry')
    if exit_day > expiry:
        return dict(row, reason='contract_expired_before_horizon')
    if exit_day > cutoff:
        return dict(row, reason='outcome_beyond_window_cutoff')
    e, x = fresh_bar(c, entry), fresh_bar(c, exit_day)
    if e is None or x is None:
        return dict(row, reason='no_fresh_entry_bar' if e is None else 'no_fresh_exit_bar')
    gross = 100*(e['close']-x['close'])
    costs = 100*haircut*(e['close']+x['close']) + 2*fee
    collateral = 100*c['strike']
    if collateral <= 0:
        raise ValueError('Nonpositive collateral.')
    # Capacity uses data strictly before entry; event-study fill proxies still require a traded bar.
    prior = [v['volume'] for d, v in sorted(c['bars'].items()) if d < entry][-20:]
    adv = sum(prior)/len(prior) if len(prior) >= 5 else 0.0
    return dict(row, status='priced', reason='', entry_mark=e['close'], exit_mark=x['close'],
                collateral=collateral, gross_pnl=gross, costs=costs, net_pnl=gross-costs,
                net_return=(gross-costs)/collateral, cost_bps=10000*costs/collateral,
                lagged_option_adv=adv, entry_volume=e['volume'], exit_volume=x['volume'],
                days_held=(date.fromisoformat(exit_day)-date.fromisoformat(entry)).days,
                exit_basis='expiry_last_trade_proxy' if horizon == 'exp' else 'daily_last_trade_proxy',
                reference_spot=c['reference_spot'], actual_reference_otm=1-c['strike']/c['reference_spot'])


def validate_dataset(data):
    if data.get('schema_version') != 1 or data.get('kind') not in ('synthetic', 'massive'):
        raise ValueError('Unknown dataset schema or provenance.')
    if data.get('mode') not in ('development', 'test', 'sealed'):
        raise ValueError('Unknown study mode.')
    seen = set()
    pair_roles = set()
    for obs in data['observations']:
        if obs['id'] in seen:
            raise ValueError('Duplicate observation ID.')
        seen.add(obs['id'])
        identity=(obs['pair_id'],obs['role'])
        if identity in pair_roles:
            raise ValueError('Duplicate role for a matched pair.')
        pair_roles.add(identity)
        if obs['available'] < obs['anchor'] or obs['role'] not in ('event', 'control'):
            raise ValueError('Invalid availability or role.')
        for c in obs['contracts']:
            if not all(math.isfinite(c[k]) and c[k]>0 for k in ('strike','reference_spot')):
                raise ValueError('Invalid contract values.')
            for d, b in c['bars'].items():
                if d > data['outcome_cutoff']:
                    raise ValueError('Dataset contains price data after the authorized outcome cutoff.')
                if not math.isfinite(b['close']) or b['close'] < 0 or not math.isfinite(b['volume']) or b['volume'] < 0:
                    raise ValueError('Invalid market bar.')
