"""Cash-secured portfolio with entry-only sizing and conservative missing-mark reserves."""
import math
from statistics import mean,stdev
from collections import Counter
from .calendar import CAL,shift
from .model import contract_for
from .execution import open_short,close_short


def assignment_cashflow(strike,spot,quantity,premium_received=0):
    """Physical assignment: strike cash paid for 100 shares/contract; optional immediate sale scenario."""
    if any(not math.isfinite(v) or v<0 for v in (strike,spot,quantity,premium_received)) or int(quantity)!=quantity:
        raise ValueError('Invalid assignment inputs.')
    shares=100*quantity
    return dict(shares_received=shares,cash_paid=strike*shares,share_value=spot*shares,
                liquidation_pnl=premium_received+(spot-strike)*shares)


def simulate(data,cfg,p):
    initial=p['initial_capital'];cash=initial;positions=[];curve=[];ledger=[];skips=Counter();peak=initial;paused=False;traded=0
    events=[o for o in data['observations'] if o['role']=='event' and o['context']=='standalone']
    entries={}
    for o in events:
        entries.setdefault(shift(o['anchor'],cfg['headline_delay']),[]).append(o)
    fee=cfg['fee_per_contract_per_side'];haircut=cfg['headline_haircut'];stale_days=0;assignment_risk_days=0
    for day in CAL:
        if not data['event_start']<=day<=data['outcome_cutoff']:continue
        retained=[]
        for pos in positions:
            q=pos['contract']['quotes'].get(day,{})
            if day>=pos['planned_exit'] and q.get('status')=='usable':
                debit=close_short(q,pos['quantity'],fee,haircut);cash-=debit;traded+=debit
                ledger.append({k:v for k,v in pos.items() if k!='contract'}|dict(exit=day,net_pnl=pos['credit']-debit,status='closed'))
            else:retained.append(pos)
        positions=retained
        def liability(pos):
            q=pos['contract']['quotes'].get(day,{})
            return min(pos['collateral'],close_short(q,pos['quantity'],fee,haircut)) if q.get('status')=='usable' else pos['collateral']
        liabilities=sum(liability(pos) for pos in positions);equity=cash-liabilities
        peak=max(peak,equity)
        if equity/peak-1<=-p['drawdown_pause']:paused=True
        for o in sorted(entries.get(day,[]),key=lambda x:x['id']):
            c=contract_for(o,cfg['headline_bucket'],cfg['headline_otm'])
            if paused:skips['drawdown_pause']+=1;continue
            if not c:skips['no_contract']+=1;continue
            if day<o['available']:skips['signal_not_available']+=1;continue
            q=c['quotes'].get(day,{})
            if q.get('status')!='usable':skips['no_usable_entry_quote']+=1;continue
            if any(x['ticker']==o['ticker'] for x in positions):skips['existing_issuer_position']+=1;continue
            # Do not condition acceptance on a future exit quote or realized profit.
            prior=[b['volume'] for d,b in sorted(c['bars'].items()) if d<day][-20:]
            adv=mean(prior) if len(prior)>=5 else 0
            if adv<p['minimum_lagged_option_adv']:skips['insufficient_lagged_liquidity']+=1;continue
            locked=sum(x['collateral'] for x in positions)
            budget=max(0,min(initial*p['issuer_fraction'],initial*p['total_collateral_fraction']-locked,cash-locked))
            qty=min(math.floor(budget/(100*c['strike']+fee)),math.floor(adv*p['adv_participation']),math.floor(q['bid_size']*p['displayed_size_fraction']))
            if qty<1:skips['capacity_below_one_contract']+=1;continue
            credit=open_short(q,qty,fee,haircut);cash+=credit;traded+=credit
            positions.append(dict(id=o['id'],ticker=o['ticker'],entry=day,planned_exit=shift(o['anchor'],cfg['headline_horizon']),
                quantity=qty,collateral=qty*100*c['strike'],credit=credit,contract=c,lagged_option_adv=adv))
        stale=any(pos['contract']['quotes'].get(day,{}).get('status')!='usable' for pos in positions)
        stale_days+=int(stale)
        assignment_risk_days+=int(bool(positions))
        equity=cash-sum(liability(x) for x in positions)
        peak=max(peak,equity)
        curve.append(dict(day=day,equity=equity,cash=cash,collateral=sum(x['collateral'] for x in positions),
                          drawdown=equity/peak-1,positions=len(positions),conservative_missing_mark=stale))
    returns=[b['equity']/a['equity']-1 for a,b in zip(curve,curve[1:]) if a['equity']>0]
    final=curve[-1]['equity'] if curve else initial;years=len(curve)/252
    vol=stdev(returns)*math.sqrt(252) if len(returns)>1 else None
    cagr=(final/initial)**(1/years)-1 if years and final>0 else None
    # Funded return includes idle cash earning zero; Sharpe uses a disclosed zero cash benchmark.
    sharpe=mean(returns)/stdev(returns)*math.sqrt(252) if len(returns)>1 and stdev(returns)>0 else None
    stress=[]
    for move in (-.2,-.5,-1):
        pnl=sum(assignment_cashflow(pos['contract']['strike'],pos['contract']['reference_spot']*(1+move),pos['quantity'],pos['credit'])['liquidation_pnl'] for pos in positions)
        stress.append(dict(reference_move=move,open_position_assignment_pnl=pnl))
    for pos in positions:ledger.append({k:v for k,v in pos.items() if k!='contract'}|dict(status='open_reserved',exit=None,net_pnl=None))
    return dict(initial_capital=initial,final_equity=final,total_return=final/initial-1,cagr=cagr,annualized_volatility=vol,
        sharpe_zero_cash=sharpe,max_drawdown=min([x['drawdown'] for x in curve],default=0),premium_cash_turnover_per_year=traded/initial/years if years else None,
        trade_count=len(ledger),closed_positions=sum(x['status']=='closed' for x in ledger),open_positions=len(positions),
        skipped=dict(skips),curve=curve,ledger=ledger,stale_mark_days=stale_days,drawdown_paused=paused,
        open_assignment_stress=stress,assignment_exposure_days=assignment_risk_days,
        limitations=['Cash-secured short puts; no leverage or premium-funded collateral expansion; idle cash return is zero.',
        'Sizing: 5% per issuer, 50% total initial capital, 1% lagged option volume, 25% displayed bid size; no overlapping issuer positions.',
        'Missing quotes reserve the entire strike liability until a fresh mark. This is a pessimistic accounting bound, not an executable price.',
        'Unclosed positions remain reserved at the cutoff; historical early assignment and stock liquidation are not observed.',
        'Turnover is traded option-premium cash divided by initial capital per year, not underlying notional turnover.',
        'A permanent new-entry pause follows a 10% marked drawdown; missing-mark reserves can trigger it.'])
