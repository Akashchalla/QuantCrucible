"""Reproducible command-line entry points; no credentials are printed."""
import argparse
import json
from edge.workflow import run
from edge.providers import ProviderError

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['check','coverage','demo','freeze','study','database-init','database-sync'])
    p.add_argument('--limit',type=int,default=12)
    p.add_argument('--kind',choices=['massive','synthetic'],default='synthetic')
    args=p.parse_args()
    try:
        result=run(args.action,{'limit':args.limit,'kind':args.kind},lambda s:print(s,flush=True))
        if args.action=='coverage':result={k:result[k] for k in ('filings','issuers','context_counts','note')}
        print(json.dumps(result,indent=2))
    except (ValueError,ProviderError) as e:p.exit(1,str(e)+'\n')
    except Exception:p.exit(1,'Operation failed; credentials were not logged. Check service access and configuration.\n')
