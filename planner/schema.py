"""Read schema metadata only. NEVER fetch real row values."""
import hashlib
import json
import sqlite3
from pathlib import Path

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def quote(name): return '"'+name.replace('"','""')+'"'

def affinity(declared):
    t=declared.upper()
    if 'INT' in t:return 'INTEGER'
    if any(x in t for x in ('CHAR','CLOB','TEXT')):return 'TEXT'
    if 'BLOB' in t or not t:return 'BLOB'
    if any(x in t for x in ('REAL','FLOA','DOUB')):return 'REAL'
    return 'NUMERIC'

def inspect_database(path):
    p=Path(path).resolve(strict=True)
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        # Restrict PRAGMA reads, SELECT and metadata reads; no ATTACH or writes.
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_RECURSIVE}
        pragmas={'table_xinfo','foreign_key_list','index_list','index_info','table_list'}
        def auth(action,arg1,arg2,*_):
            if action in allowed:return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_PRAGMA and arg1.lower() in pragmas:return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        db.set_authorizer(auth)
        objects=db.execute("SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        if len(objects)>100:raise ValueError('Schema has over 100 objects; narrow the database before planning')
        table_flags={r[1]:{'without_rowid':bool(r[4]),'strict':bool(r[5])} for r in db.execute('PRAGMA table_list')}
        tables={}; unsupported=[]
        for name,kind,sql in objects:
            if kind=='view' or (sql or '').upper().startswith('CREATE VIRTUAL'):
                unsupported.append({'name':name,'reason':'View or virtual table requires separate review'});continue
            columns=[]
            for row in db.execute(f'PRAGMA table_xinfo({quote(name)})'):
                cid,col,typ,notnull,default,pk,hidden=row
                columns.append({'name':col,'declared_type':typ,'affinity':affinity(typ),
                    'nullable':not bool(notnull),'sqlite_notnull':bool(notnull),'primary_key_position':pk,
                    'has_default':default is not None,'generated':bool(hidden),
                    'default_note':'Declared default exists; expression withheld' if default is not None else None})
            if len(columns)>200:raise ValueError('Table has over 200 columns')
            pk=[c['name'] for c in sorted(columns,key=lambda c:c['primary_key_position']) if c['primary_key_position']]
            groups={}
            for fid,seq,parent,child_col,parent_col,on_update,on_delete,match in db.execute(f'PRAGMA foreign_key_list({quote(name)})'):
                group=groups.setdefault(fid,{'parent_table':parent,'columns':[],'parent_columns':[],'on_update':on_update,'on_delete':on_delete})
                group['columns'].append(child_col);group['parent_columns'].append(parent_col)
            unique=[]
            indexes=list(db.execute(f'PRAGMA index_list({quote(name)})'))
            flags=table_flags.get(name,{})
            integer_alias=len(pk)==1 and any(c['name']==pk[0] and c['declared_type'].upper()=='INTEGER' for c in columns) and not any(idx[3]=='pk' for idx in indexes)
            for c in columns:
                if c['primary_key_position'] and (integer_alias or flags.get('without_rowid') or flags.get('strict')):c['nullable']=False
            for idx in indexes:
                if idx[2] and not idx[4]:
                    cols=[x[2] for x in db.execute(f'PRAGMA index_info({quote(idx[1])})')]
                    if all(cols):unique.append(cols)
            examples=[]
            for i in (1,2):
                examples.append({c['name']: i if c['affinity']=='INTEGER' else float(i) if c['affinity'] in ('REAL','NUMERIC') else '<synthetic bytes>' if c['affinity']=='BLOB' else f'synthetic_value_{i}' for c in columns})
            tables[name]={'definition_sha256':hashlib.sha256((sql or '').encode()).hexdigest(),'columns':columns,'primary_key':pk,'unique_keys':unique,'foreign_keys':list(groups.values()),
                          'synthetic_sample_rows':examples,'sample_provenance':'Generated from types. Not observed values; not semantic evidence.'}
        for table in tables.values():
            for fk in table['foreign_keys']:
                if any(c is None for c in fk['parent_columns']) and fk['parent_table'] in tables:
                    fk['parent_columns']=tables[fk['parent_table']]['primary_key']
        summary={'tables':tables,'unsupported_objects':unsupported,
                 'privacy':'No real rows or default expressions were read into the model payload.'}
        return summary
