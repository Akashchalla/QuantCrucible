"""Judge entry point: identical frozen strategy for development, test and unseen windows."""
import argparse,json
from edge.study import run_window,freeze_v2
from edge.runtime import ROOT

def run_study(start_date,end_date,mode='sealed',progress=print):
    return run_window(start_date,end_date,mode,progress)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start',default='2024-01-01');p.add_argument('--end',default='2025-12-31')
    p.add_argument('--mode',choices=['development','test','sealed'],default='development')
    p.add_argument('--freeze-only',action='store_true');args=p.parse_args()
    try:
        r=freeze_v2() if args.freeze_only else run_study(args.start,args.end,args.mode)
        print(json.dumps({k:r[k] for k in ('created_at','source_hash','run_id','mode','event_count','decision') if k in r},indent=2))
    except Exception as e:
        # No raw HTTP/DB diagnostics or secrets in public output.
        from edge.providers import ProviderError
        p.exit(1,(str(e) if isinstance(e,(ValueError,ProviderError)) else 'Research operation failed; inspect local configuration and retry unchanged.')+'\n')
