import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from examples.create_databases import create,CONTEXT_A,CONTEXT_B
from planner.service import PlannerSession
from planner.schema import inspect_database
from planner.validation import validate_plan
from planner.models import ProposedPlan,UnresolvedField
from planner.adapter import OpenAICompatibleAdapter
from fixtures import FixtureAdapter,fixture_plan

DECISION={'action':'approve','reviewer':'Test reviewer','reason':'Reviewed mappings against the synthetic business specification.'}

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);create(self.root/'dbs')
    def db(self,pair,side):return self.root/f'dbs/pair_{pair}_{side}.sqlite'
    def start(self,adapter=None,pair='a',run='run'):
        adapter=adapter or FixtureAdapter(pair)
        session=PlannerSession(self.root/run,adapter)
        status=session.start(self.db(pair,'old'),self.db(pair,'new'),CONTEXT_A if pair=='a' else CONTEXT_B)
        return session,status,adapter
    def test_valid_mapping_pauses_then_resumes_same_run(self):
        session,status,adapter=self.start()
        self.assertEqual(status['review_status'],'awaiting_approval')
        self.assertFalse(status['final_plan_available'])
        with self.assertRaises(ValueError):session.final_plan()
        result=PlannerSession(self.root/'run').resume(DECISION)
        self.assertEqual(result['run_id'],status['run_id'])
        self.assertEqual(result['review_status'],'approved')
        plan=session.final_plan()
        self.assertEqual(len(plan.table_mappings),4)
        self.assertEqual(len(plan.relationships),3)
        self.assertEqual(adapter.calls,1)
        with self.assertRaises(ValueError):session.resume(DECISION)
    def test_second_pair_same_agent_and_unit_transforms(self):
        session,status,_=self.start(pair='b')
        self.assertFalse(status['validation_errors'])
        session.resume(DECISION)
        fields=[f for t in session.final_plan().table_mappings for f in t.fields]
        self.assertEqual({f.transformation.factor for f in fields if f.transformation.kind=='unit_scale'},{'0.001','0.01'})
    def test_ambiguous_mapping_interrupts_and_cannot_be_approved(self):
        def ambiguous(p):
            p.table_mappings[0].fields[1].status='needs_review'
            p.unresolved_fields.append(UnresolvedField(side='source',table='patrons',column='display_name',reason='Could mean legal name or display alias.'))
        session,status,_=self.start(FixtureAdapter(mutation=ambiguous))
        self.assertEqual(status['review_status'],'needs_review')
        result=session.resume(DECISION)
        self.assertFalse(result['final_plan_available'])
        self.assertEqual(result['review_status'],'blocked')
    def test_nonexistent_column_edit_revalidate_approve(self):
        def bad(p):p.table_mappings[0].fields[1].source_column='does_not_exist'
        session,status,_=self.start(FixtureAdapter(mutation=bad))
        self.assertIn('unknown_column',{x['code'] for x in status['validation_errors']})
        self.assertFalse(session.resume(DECISION)['final_plan_available'])
        good=fixture_plan('a',inspect_database(self.db('a','old')))
        edited=session.resume({'action':'edit','reviewer':'Test reviewer','reason':'Corrected the invented source column.','plan':good.model_dump()})
        self.assertEqual(edited['review_status'],'awaiting_approval')
        self.assertFalse(edited['final_plan_available'])
        self.assertTrue(session.resume(DECISION)['final_plan_available'])
    def test_rejection_emits_no_plan(self):
        session,_,_=self.start()
        result=session.resume({'action':'reject','reviewer':'Test reviewer','reason':'Wrong interpretation.'})
        self.assertEqual(result['review_status'],'rejected')
        self.assertFalse((self.root/'run/final_plan.json').exists())
    def test_missing_required_destination(self):
        def bad(p):p.table_mappings[0].fields.pop()
        _,status,_=self.start(FixtureAdapter(mutation=bad))
        self.assertIn('required_destination',{e['code'] for e in status['validation_errors']})
    def test_missing_record_type_is_not_silently_discarded(self):
        def bad(p):p.table_mappings.pop()
        _,status,_=self.start(FixtureAdapter(mutation=bad))
        self.assertIn('unmapped_source_table',{e['code'] for e in status['validation_errors']})
    def test_broken_relationship(self):
        def bad(p):p.relationships[0].destination_parent_columns=['name']
        _,status,_=self.start(FixtureAdapter(mutation=bad))
        self.assertIn('invalid_destination_relationship',{e['code'] for e in status['validation_errors']})
    def test_duplicate_destination_mapping(self):
        def bad(p):p.table_mappings[0].fields.append(copy.deepcopy(p.table_mappings[0].fields[0]))
        _,status,_=self.start(FixtureAdapter(mutation=bad))
        self.assertIn('duplicate_destination',{e['code'] for e in status['validation_errors']})
    def test_databases_unchanged(self):
        files=[self.db('a',side) for side in ('old','new')];before=[sha(p) for p in files]
        session,_,_=self.start();session.resume(DECISION)
        self.assertEqual(before,[sha(p) for p in files])
    def test_real_rows_and_default_values_never_enter_payload(self):
        with sqlite3.connect(self.db('a','old')) as db:
            db.execute("UPDATE patrons SET display_name='PRIVATE_PERSON_SENTINEL'")
            db.execute("ALTER TABLE patrons ADD COLUMN private_default TEXT DEFAULT 'PRIVATE_DEFAULT_SENTINEL'")
        summary=inspect_database(self.db('a','old'))
        self.assertNotIn('PRIVATE_PERSON_SENTINEL',json.dumps(summary))
        self.assertNotIn('PRIVATE_DEFAULT_SENTINEL',json.dumps(summary))
        self.assertEqual(len(summary['tables']['patrons']['synthetic_sample_rows']),2)
    def test_schema_drift_blocks_approval(self):
        session,_,_=self.start()
        with sqlite3.connect(self.db('a','new')) as db:db.execute('ALTER TABLE customers ADD COLUMN extra TEXT')
        result=session.resume(DECISION)
        self.assertIn('schema_changed',{e['code'] for e in result['validation_errors']})
        self.assertFalse(result['final_plan_available'])
    def test_invalid_review_pauses_again(self):
        session,_,_=self.start()
        result=session.resume({'action':'edit','reviewer':'Test reviewer','reason':'Missing replacement plan'})
        self.assertEqual(result['review_status'],'invalid_review')
        self.assertFalse(result['final_plan_available'])
        self.assertTrue(session.resume(DECISION)['final_plan_available'])
    def test_no_key_means_no_mapping_fallback(self):
        with patch.dict('os.environ',{'MIGRATION_API_KEY':'','OPENAI_API_KEY':''}):
            with self.assertRaisesRegex(ValueError,'No fake mapping'):OpenAICompatibleAdapter()
    def test_source_and_destination_must_be_distinct(self):
        with self.assertRaises(ValueError):PlannerSession(self.root/'run',FixtureAdapter()).start(self.db('a','old'),self.db('a','old'))
    def test_checkpoint_cannot_alias_input_database(self):
        import os
        out=self.root/'run';out.mkdir()
        os.link(self.db('a','old'),out/'checkpoint.sqlite')
        before=sha(self.db('a','old'))
        with self.assertRaises(ValueError):PlannerSession(out,FixtureAdapter()).start(self.db('a','old'),self.db('a','new'))
        self.assertEqual(before,sha(self.db('a','old')))
    def test_inspect_composite_keys_and_quoted_names(self):
        path=self.root/'composite.sqlite'
        with sqlite3.connect(path) as db:
            db.executescript('CREATE TABLE "odd parent" (a INTEGER NOT NULL,b INTEGER NOT NULL,PRIMARY KEY(a,b)); CREATE TABLE child(x INTEGER NOT NULL,y INTEGER NOT NULL,FOREIGN KEY(x,y) REFERENCES "odd parent"(a,b));')
        s=inspect_database(path)
        self.assertEqual(s['tables']['odd parent']['primary_key'],['a','b'])
        self.assertEqual(s['tables']['child']['foreign_keys'][0]['parent_columns'],['a','b'])
    def test_missing_database_is_not_created(self):
        path=self.root/'missing.sqlite'
        with self.assertRaises(FileNotFoundError):inspect_database(path)
        self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
