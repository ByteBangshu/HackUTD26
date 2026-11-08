"""Prepare a review payload, never modifying an input database."""
import argparse
import json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--output',required=True);a=p.parse_args()
root=Path(a.run_dir);manifest=json.loads((root/'run.json').read_text());target=Path(a.output).resolve()
for name in ('source_path','destination_path'):
    source=Path(manifest[name]).resolve()
    if target==source or target.exists() and target.samefile(source):raise ValueError('Cannot write review JSON over an input database')
if target.exists():raise FileExistsError('Output exists; choose a new path or edit the existing review file')
proposal=json.loads((root/'proposal.json').read_text())
target.write_text(json.dumps({'action':'edit','reviewer':'REPLACE WITH YOUR NAME','reason':'REPLACE WITH THE EVIDENCE FOR YOUR EDIT','plan':proposal},indent=2))
print(target)
