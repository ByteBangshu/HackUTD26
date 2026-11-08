"""Public planning interface. Checkpoints/artifacts are separate from input DBs."""
from contextlib import contextmanager
import json
from pathlib import Path
import uuid
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from .adapter import OpenAICompatibleAdapter
from .graph import build_graph
from .models import MigrationPlan

class ResumeOnlyAdapter:
    origin='llm'
    def propose(self,*args):raise RuntimeError('Resume must not regenerate the mapping')

class PlannerSession:
    def __init__(self,run_directory,adapter=None):
        self.root=Path(run_directory).resolve()
        self.adapter=adapter
    def _manifest(self):return json.loads((self.root/'run.json').read_text())
    def _protect(self,source,destination):
        protected={Path(source).resolve(),Path(destination).resolve()}
        for name in ('checkpoint.sqlite','checkpoint.sqlite-wal','checkpoint.sqlite-shm','run.json','status.json','proposal.json','final_plan.json','events.jsonl'):
            target=self.root/name
            if target.resolve() in protected or any(target.exists() and target.samefile(p) for p in protected):
                raise ValueError('Run artifacts must be separate from source/destination databases')
    @contextmanager
    def _graph(self,adapter):
        with SqliteSaver.from_conn_string(str(self.root/'checkpoint.sqlite')) as saver:
            yield build_graph(adapter,saver)
    def _save(self,values):
        self._protect(values['source_path'],values['destination_path'])
        for key,name in [('proposed_plan','proposal.json'),('final_plan','final_plan.json')]:
            if values.get(key) is not None:(self.root/name).write_text(json.dumps(values[key],indent=2))
        (self.root/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in values.get('events',[])))
        status={k:values.get(k) for k in ('run_id','review_status','validation_errors','uncertainties','mapping_origin')}
        status['final_plan_available']=values.get('final_plan') is not None
        (self.root/'status.json').write_text(json.dumps(status,indent=2))
        return status
    def start(self,source,destination,context=''):
        source=str(Path(source).resolve(strict=True));destination=str(Path(destination).resolve(strict=True))
        if Path(source).samefile(destination):raise ValueError('Source and destination must be distinct databases')
        self._protect(source,destination)
        if self.root.exists() and any(self.root.iterdir()):raise ValueError('Use a new empty run directory, or resume the existing run')
        adapter=self.adapter or OpenAICompatibleAdapter()
        self.root.mkdir(parents=True,exist_ok=True)
        run_id=uuid.uuid4().hex
        (self.root/'run.json').write_text(json.dumps({'run_id':run_id,'source_path':source,'destination_path':destination},indent=2))
        state={'run_id':run_id,'source_path':source,'destination_path':destination,'context':context,'events':[],
               'proposed_plan':None,'final_plan':None,'validation_errors':[],'uncertainties':[],'review_status':'draft'}
        with self._graph(adapter) as graph:
            result=graph.invoke(state,{'configurable':{'thread_id':run_id}})
            return self._save(result)
    def resume(self,decision):
        m=self._manifest();self._protect(m['source_path'],m['destination_path'])
        with self._graph(self.adapter or ResumeOnlyAdapter()) as graph:
            config={'configurable':{'thread_id':m['run_id']}}
            snapshot=graph.get_state(config)
            if not snapshot.next or not any(t.interrupts for t in snapshot.tasks):raise ValueError('Run is complete or not paused for human review; it cannot be resumed')
            result=graph.invoke(Command(resume=decision),config)
            return self._save(result)
    def final_plan(self)->MigrationPlan:
        m=self._manifest();self._protect(m['source_path'],m['destination_path'])
        with self._graph(ResumeOnlyAdapter()) as graph:
            snapshot=graph.get_state({'configurable':{'thread_id':m['run_id']}})
            value=snapshot.values.get('final_plan')
            if snapshot.next or snapshot.values.get('review_status')!='approved' or not value:
                raise ValueError('No completed, approved MigrationPlan available')
            return MigrationPlan.model_validate(value)
