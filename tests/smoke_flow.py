"""First end-to-end graph exercise. Test fixture, not simulated AI marketing."""
import json
import tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from examples.create_databases import create,CONTEXT_A
from planner.service import PlannerSession
from fixtures import FixtureAdapter

if __name__=='__main__':
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);create(root/'dbs')
        adapter=FixtureAdapter()
        session=PlannerSession(root/'run',adapter)
        print(session.start(root/'dbs/pair_a_old.sqlite',root/'dbs/pair_a_new.sqlite',CONTEXT_A))
        resumed=PlannerSession(root/'run').resume({'action':'approve','reviewer':'Synthetic test reviewer','reason':'Reviewed against the synthetic dictionary.'})
        print(resumed)
        plan=session.final_plan()
        print('Final tables:',len(plan.table_mappings),'LLM calls:',0,'test adapter calls:',adapter.calls)
        Path('examples/sample_migration_plan.json').write_text(plan.model_dump_json(indent=2))
