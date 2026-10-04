"""Explain deployment blockers. Review thresholds are policies, not statistical guarantees."""
def assess(report):
    if not report:return {'decision':'No completed report','checks':[]}
    h=next(x for x in report['horizons'] if x['horizon']==21)['groups']['standalone']
    pf=report.get('portfolio',{})
    checks=[
        {'name':'Real historical evidence','passed':report['kind']=='massive','detail':'Synthetic examples cannot support an allocation.'},
        {'name':'Positive primary relative result','passed':h.get('edge') is not None and h['edge']>0,'detail':'A positive comparison is necessary for this hypothesis, not proof of absolute profit.'},
        {'name':'Minimum research coverage','passed':h.get('pairs',0)>=20 and h.get('issuers',0)>=10 and h.get('calendar_clusters',0)>=8,'detail':f"{h.get('pairs',0)} pairs, {h.get('issuers',0)} issuers, {h.get('calendar_clusters',0)} quarters. Review policy: at least 20 / 10 / 8. These thresholds do not guarantee valid inference."},
        {'name':'Positive funded account result','passed':pf.get('total_return',0)>0,'detail':'After cash limits, quote costs and missing-mark reserves.'},
        {'name':'Historical information arrival verified','passed':False,'detail':'Classifications were not archived at the historical decision time.'},
        {'name':'Assignment and actual fills verified','passed':False,'detail':'NBBO and assignment scenarios are simulations, not observed broker executions.'}
    ]
    return {'decision':'Research only','checks':checks,'passed':sum(c['passed'] for c in checks),'total':len(checks),
            'note':'Passing a checklist would still require independent research and operational approval. This application cannot authorize or place trades.'}
