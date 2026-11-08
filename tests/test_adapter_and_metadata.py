import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from planner.adapter import OpenAICompatibleAdapter
from planner.schema import inspect_database
from fixtures import fixture_plan
from examples.create_databases import create

class MetadataTests(unittest.TestCase):
    def test_sqlite_nullable_text_primary_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'db.sqlite'
            with sqlite3.connect(p) as db:
                db.executescript('CREATE TABLE text_key(id TEXT PRIMARY KEY); CREATE TABLE int_key(id INTEGER PRIMARY KEY); CREATE TABLE composite(a TEXT,b TEXT,PRIMARY KEY(a,b));')
            s=inspect_database(p)['tables']
            self.assertTrue(s['text_key']['columns'][0]['nullable'])
            self.assertFalse(s['int_key']['columns'][0]['nullable'])
            self.assertTrue(all(c['nullable'] for c in s['composite']['columns']))
    def test_openai_compatible_configuration_and_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            create(tmp)
            source=inspect_database(Path(tmp)/'pair_a_old.sqlite')
            dest=inspect_database(Path(tmp)/'pair_a_new.sqlite')
            response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=fixture_plan('a',source).model_dump_json()))])
            with patch.dict(os.environ,{'MIGRATION_API_KEY':'test-secret','MIGRATION_API_URL':'https://example.invalid/v1','MIGRATION_MODEL':'test-model'}),patch('openai.OpenAI') as factory:
                factory.return_value.chat.completions.create.return_value=response
                adapter=OpenAICompatibleAdapter();result=adapter.propose(source,dest,'Synthetic data dictionary only')
                self.assertEqual(factory.call_args.kwargs['base_url'],'https://example.invalid/v1')
                args=factory.return_value.chat.completions.create.call_args.kwargs
                self.assertEqual(args['model'],'test-model')
                self.assertNotIn('test-secret',json.dumps(args))
                self.assertNotIn('Synthetic Guest A',args['messages'][1]['content'])
                self.assertEqual(len(result.table_mappings),4)
    def test_malformed_provider_plan_is_rejected(self):
        with patch.dict(os.environ,{'MIGRATION_API_KEY':'test-secret'}),patch('openai.OpenAI') as factory:
            factory.return_value.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"pretend_approved":true}'))])
            with self.assertRaises(ValueError):OpenAICompatibleAdapter().propose({}, {}, '')
