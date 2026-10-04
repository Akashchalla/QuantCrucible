"""Execution evidence from timestamped NBBO quotes; never a guarantee of a fill."""
import math
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from .calendar import CAL

EASTERN=ZoneInfo('America/New_York')
# NYSE scheduled early closes within supported challenge years. Exceptional full closures are in calendar.py.
EARLY={'2022-11-25','2023-07-03','2023-11-24','2024-07-03','2024-11-29','2024-12-24',
       '2025-07-03','2025-11-28','2025-12-24','2026-11-27','2026-12-24',
       '2027-11-26'}


def decision_time(day):
    # Five minutes before the close, including early-close days, rather than a quote after the bell.
    return datetime.fromisoformat(day+('T12:55:00' if day in EARLY else 'T15:55:00')).replace(tzinfo=EASTERN)


def quote(m,ticker,day,cfg):
    if day not in CAL:raise ValueError('Quote day must be a supported trading session.')
    deadline=decision_time(day); ns=int(deadline.timestamp())*10**9
    r=m.get('/v3/quotes/'+ticker,{'timestamp.gte':ns-cfg['quote_max_age_seconds']*10**9,
           'timestamp.lte':ns,'sort':'timestamp','order':'desc','limit':1})
    rows=r.get('results',[])
    if not rows:return {'status':'unavailable','reason':'no_recent_quote','decision_at':deadline.isoformat()}
    q=rows[0];bid=q.get('bid_price',0);ask=q.get('ask_price',0)
    result=dict(bid=bid,ask=ask,bid_size=q.get('bid_size',0),ask_size=q.get('ask_size',0),
        sip_timestamp=q.get('sip_timestamp',0),decision_at=deadline.isoformat(),source='Massive NBBO',status='unavailable')
    if any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in (bid,ask,result['bid_size'],result['ask_size'],result['sip_timestamp'])):
        return dict(result,reason='nonfinite_quote')
    mid=(bid+ask)/2
    if min(bid,ask)<=0 or ask<bid:result['reason']='invalid_or_crossed_quote'
    elif min(result['bid_size'],result['ask_size'])<1:result['reason']='empty_displayed_size'
    elif mid<cfg['minimum_option_mid']:result['reason']='premium_below_minimum'
    elif (ask-bid)/mid>cfg['maximum_relative_spread']:result['reason']='spread_too_wide'
    elif not 0<=ns-result['sip_timestamp']<=cfg['quote_max_age_seconds']*10**9:result['reason']='quote_timestamp_outside_window'
    else:result.update(status='usable',reason='',relative_spread=(ask-bid)/mid,age_seconds=(ns-result['sip_timestamp'])/1e9)
    return result


def close_short(q,quantity,fee,haircut):
    return quantity*(100*q['ask']*(1+haircut)+fee)


def open_short(q,quantity,fee,haircut):
    return quantity*(100*q['bid']*(1-haircut)-fee)
