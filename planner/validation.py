from decimal import Decimal, InvalidOperation
from .models import ProposedPlan

def validate_plan(plan:ProposedPlan,source:dict,destination:dict):
    errors=[];uncertain=[]
    def error(code,message):errors.append({'code':code,'message':message})
    src,dst=source['tables'],destination['tables']
    cols=lambda t:{c['name']:c for c in t['columns']}
    pairs={};target_seen=set(); mapped_source=set(); mapped_dest=set();field_edges=set()
    for side,summary in [('source',source),('destination',destination)]:
        for item in summary['unsupported_objects']:error('unsupported_object',f'{side}: {item["name"]} requires manual scope resolution')
    for table in plan.table_mappings:
        s,d=table.source_table,table.destination_table
        if s not in src or d not in dst:
            error('unknown_table',f'Unknown table mapping {s} -> {d}');continue
        if s in pairs or d in target_seen:error('table_conflict',f'Only one-to-one table mappings supported: {s} -> {d}')
        pairs[s]=d;target_seen.add(d)
        sc,dc=cols(src[s]),cols(dst[d]);dest_fields=set()
        for f in table.fields:
            a,b=f.source_column,f.destination_column;t=f.transformation
            if b not in dc or (a is not None and a not in sc):
                error('unknown_column',f'Unknown field {s}.{a} -> {d}.{b}');continue
            if b in dest_fields:error('duplicate_destination',f'Multiple assignments to {d}.{b}')
            dest_fields.add(b);mapped_dest.add((d,b))
            if dc[b]['generated']:error('generated_destination',f'Cannot assign generated field {d}.{b}')
            if a is not None:mapped_source.add((s,a));field_edges.add((s,a,d,b))
            needed={f'destination:{d}.{b}'} | ({f'source:{s}.{a}'} if a is not None else set())
            if not needed.issubset(f.evidence):error('missing_evidence',f'Field endpoints missing from evidence: {s}.{a} -> {d}.{b}')
            known={f'{side}:{tn}.{c["name"]}' for side,summary in [('source',source),('destination',destination)] for tn,tb in summary['tables'].items() for c in tb['columns']}
            if any(e not in known for e in f.evidence):error('invented_evidence',f'Unknown evidence for {d}.{b}')
            if f.status=='needs_review' or f.confidence<0.8:uncertain.append(f'{s}.{a} -> {d}.{b}: {f.explanation}')
            if a is None and t.kind!='constant':error('missing_source',f'{d}.{b} needs a source or explicit constant')
            if a is not None and t.kind=='constant':error('constant_source',f'Constant must not silently discard {s}.{a}')
            if t.kind=='constant' and t.constant is None and not dc[b]['nullable']:error('null_required',f'Null constant for required {d}.{b}')
            if a is not None and sc[a]['nullable'] and not dc[b]['nullable']:
                error('nullability',f'{s}.{a} allows NULL but {d}.{b} does not; source constraints or an explicit future null policy required')
            if a is not None and sc[a]['affinity']!=dc[b]['affinity'] and t.kind not in ('cast','unit_scale'):
                error('type_change',f'{s}.{a} -> {d}.{b} requires an explicit conversion')
            if t.kind=='unit_scale':
                try:
                    factor=Decimal(t.factor or '')
                    if not factor.is_finite() or factor<=0:raise ValueError()
                except (InvalidOperation,ValueError):error('invalid_scale',f'Invalid unit factor for {d}.{b}')
                if not t.from_unit or not t.to_unit:error('missing_units',f'Units required for {d}.{b}')
                if a is None or sc[a]['affinity'] not in ('INTEGER','REAL','NUMERIC') or dc[b]['affinity'] not in ('INTEGER','REAL','NUMERIC'):error('nonnumeric_scale',f'Unit conversion requires numeric endpoints: {d}.{b}')
            if t.kind=='enum_translate' and not t.value_map:error('missing_enum_map',f'Enum mapping required for {d}.{b}')
            if t.kind=='cast' and t.target_type != dc[b]['affinity']:error('invalid_cast',f'Explicit SQLite affinity required for {d}.{b}')
    for s,table in src.items():
        if s not in pairs:error('unmapped_source_table',f'Source record type {s} is not mapped')
        for c in table['columns']:
            if (s,c['name']) not in mapped_source:error('unmapped_source_column',f'Source field {s}.{c["name"]} is not accounted for')
    for d,table in dst.items():
        for c in table['columns']:
            if not c['nullable'] and not c['has_default'] and not c['generated'] and (d,c['name']) not in mapped_dest:
                error('required_destination',f'Required destination field {d}.{c["name"]} is not mapped')
    # A destination unique/primary key must derive from a declared source key.
    for tm in plan.table_mappings:
        if tm.source_table not in src or tm.destination_table not in dst:continue
        source_table=src[tm.source_table];destination_table=dst[tm.destination_table]
        assignments={f.destination_column:f for f in tm.fields}
        for key in [destination_table['primary_key'],*destination_table['unique_keys']]:
            if not key:continue
            fields=[assignments.get(c) for c in key]
            if not all(fields):
                error('unmapped_unique_key',f'Destination key requires explicit preserved values: {tm.destination_table} {key}');continue
            source_key=[f.source_column for f in fields]
            if source_key not in [source_table['primary_key'],*source_table['unique_keys']]:
                error('uniqueness_not_supported',f'Destination key {tm.destination_table} {key} is not backed by a declared source key')
            if any(f.transformation.kind not in ('identity','rename') for f in fields):
                error('key_transformation',f'Key conversion requires an extended collision policy: {tm.destination_table} {key}')
    def signature(child,fk):return (child,tuple(fk['columns']),fk['parent_table'],tuple(fk['parent_columns']))
    sfks={signature(n,fk) for n,t in src.items() for fk in t['foreign_keys']}
    dfks={signature(n,fk) for n,t in dst.items() for fk in t['foreign_keys']}
    covered_s=set();covered_d=set()
    for r in plan.relationships:
        a=(r.source_child_table,tuple(r.source_child_columns),r.source_parent_table,tuple(r.source_parent_columns))
        b=(r.destination_child_table,tuple(r.destination_child_columns),r.destination_parent_table,tuple(r.destination_parent_columns))
        if a not in sfks:error('invalid_source_relationship',f'Source FK does not exist: {a}')
        if b not in dfks:error('invalid_destination_relationship',f'Destination FK does not exist: {b}')
        if a in covered_s or b in covered_d:error('duplicate_relationship','Relationship mapped more than once')
        covered_s.add(a);covered_d.add(b)
        if not len(a[1])==len(a[3])==len(b[1])==len(b[3]):error('key_arity','Foreign key column counts differ');continue
        for st,ss,dt,dd in [(a[0],a[1],b[0],b[1]),(a[2],a[3],b[2],b[3])]:
            if pairs.get(st)!=dt:error('relationship_table_mismatch',f'FK table mapping mismatch: {st} -> {dt}')
            for x,y in zip(ss,dd):
                if (st,x,dt,y) not in field_edges:error('relationship_field_mismatch',f'FK fields do not map: {st}.{x} -> {dt}.{y}')
        for tables,sig in [(src,a),(dst,b)]:
            parent=tables.get(sig[2])
            if parent and list(sig[3]) not in [parent['primary_key'],*parent['unique_keys']]:error('parent_not_unique',f'FK parent not declared unique: {sig[2]} {sig[3]}')
        if r.strategy=='id_lookup':error('unsupported_id_lookup','Generated-ID lookup requires a separately specified transfer strategy; preserve_ids is the supported v1 contract')
        if r.strategy=='preserve_ids':
            ends={(a[0],x,b[0],y) for x,y in zip(a[1],b[1])}|{(a[2],x,b[2],y) for x,y in zip(a[3],b[3])}
            for tm in plan.table_mappings:
                for f in tm.fields:
                    if (tm.source_table,f.source_column,tm.destination_table,f.destination_column) in ends and f.transformation.kind not in ('identity','rename'):
                        error('id_value_change','preserve_ids requires identity/rename at both FK endpoints')
    for fk in sfks-covered_s:error('unmapped_source_relationship',f'Source relationship missing: {fk}')
    for fk in dfks-covered_d:error('unmapped_destination_relationship',f'Destination relationship missing: {fk}')
    for u in plan.unresolved_fields:
        tables=src if u.side=='source' else dst
        if u.table not in tables or u.column is not None and u.column not in cols(tables[u.table]):error('unknown_unresolved',f'Unresolved reference does not exist: {u.table}.{u.column}')
        uncertain.append(f'{u.side}:{u.table}.{u.column}: {u.reason}')
    return errors,uncertain
