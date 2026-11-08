import argparse
import json
import logging
from pathlib import Path
from .service import PlannerSession

def main():
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    parser=argparse.ArgumentParser(description='Read-only SQLite migration planning with human review')
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--source',required=True);run.add_argument('--destination',required=True);run.add_argument('--run-dir',required=True);run.add_argument('--context-file')
    resume=sub.add_parser('resume');resume.add_argument('--run-dir',required=True);resume.add_argument('--decision',required=True,help='Path to JSON ReviewDecision')
    status=sub.add_parser('status');status.add_argument('--run-dir',required=True)
    args=parser.parse_args()
    try:
        if args.command=='run':
            context=Path(args.context_file).read_text() if args.context_file else ''
            if len(context)>20000:raise ValueError('Context must be under 20,000 characters; use non-personal schema definitions only')
            result=PlannerSession(args.run_dir).start(args.source,args.destination,context)
        elif args.command=='resume':result=PlannerSession(args.run_dir).resume(json.loads(Path(args.decision).read_text()))
        else:result=json.loads((Path(args.run_dir)/'status.json').read_text())
        print(json.dumps(result,indent=2))
    except Exception as exc:
        # Provider errors may contain request data. Do not print raw payloads/secrets.
        if isinstance(exc,(ValueError,FileNotFoundError)):message=str(exc)
        else:message=f'{type(exc).__name__}: planning stopped; check database paths, provider configuration or availability. No fallback mapping was generated.'
        parser.exit(1,message+'\n')
if __name__=='__main__':main()
