import logging
import sqlite3
from datetime import datetime,timezone
from typing import TypedDict
from langgraph.graph import StateGraph,START,END
from langgraph.types import interrupt
from .models import ProposedPlan,MigrationPlan,ReviewDecision
from .schema import inspect_database,digest
from .validation import validate_plan

log=logging.getLogger('migration_planner')
class PlannerState(TypedDict,total=False):
    run_id:str
    source_path:str
    destination_path:str
    context:str
    source_schema:dict
    destination_schema:dict
    proposed_plan:dict|None
    validation_errors:list[dict]
    uncertainties:list[str]
    review_status:str
    review_decision:dict|None
    final_plan:dict|None
    events:list[dict]
    mapping_origin:str
    schema_changed:bool

def event(state,node,message,**details):
    record={'time':datetime.now(timezone.utc).isoformat(),'node':node,'message':message,**details}
    log.info('%s: %s',node,message)
    return state.get('events',[])+[record]

def build_graph(adapter,checkpointer):
    def inspect(state):
        source=inspect_database(state['source_path']);dest=inspect_database(state['destination_path'])
        return {'source_schema':source,'destination_schema':dest,'review_status':'draft','final_plan':None,
                'events':event(state,'inspect','Read schema metadata; no real rows collected',source_tables=len(source['tables']),destination_tables=len(dest['tables']))}
    def propose(state):
        plan=adapter.propose(state['source_schema'],state['destination_schema'],state.get('context',''))
        plan=ProposedPlan.model_validate(plan)
        return {'proposed_plan':plan.model_dump(),'mapping_origin':adapter.origin,
                'events':event(state,'propose','Received structured mapping proposal',origin=adapter.origin,explanation=plan.explanation)}
    def validate(state):
        errors,uncertain=validate_plan(ProposedPlan.model_validate(state['proposed_plan']),state['source_schema'],state['destination_schema'])
        return {'validation_errors':errors,'uncertainties':uncertain,'review_status':'needs_review' if errors or uncertain else 'awaiting_approval',
                'events':event(state,'validate','Validated references, coverage and declared relationships',errors=errors,uncertainties=uncertain)}
    def assess(state):
        return {'events':event(state,'flag_review','Proposal has unresolved or structurally invalid mappings; approval is blocked until edited')}
    def human_review(state):
        answer=interrupt({'run_id':state['run_id'],'status':state['review_status'],'proposal':state['proposed_plan'],
            'validation_errors':state['validation_errors'],'uncertainties':state['uncertainties'],
            'actions':['approve','edit','reject'],'instruction':'Approve only after semantic review. Edits are revalidated and pause for a separate approval. Unresolved mappings cannot be approved.'})
        try:
            decision=ReviewDecision.model_validate(answer)
            if decision.action=='edit' and decision.plan is None:raise ValueError('edit requires a complete ProposedPlan')
            if decision.action!='edit' and decision.plan is not None:raise ValueError('Only edit may supply a replacement plan')
        except ValueError as exc:
            return {'review_status':'invalid_review','review_decision':None,
                    'events':event(state,'human_review','Invalid review payload; waiting again',error=str(exc))}
        update={'review_decision':decision.model_dump(),'review_status':decision.action,
                'events':event(state,'human_review','Human decision received',action=decision.action,reviewer=decision.reviewer,reason=decision.reason)}
        if decision.action=='edit':update['proposed_plan']=decision.plan.model_dump()
        return update
    def gate(state):
        errors,uncertain=validate_plan(ProposedPlan.model_validate(state['proposed_plan']),state['source_schema'],state['destination_schema'])
        try:
            current_s=inspect_database(state['source_path']);current_d=inspect_database(state['destination_path'])
            changed=digest(current_s)!=digest(state['source_schema']) or digest(current_d)!=digest(state['destination_schema'])
        except (OSError,ValueError,sqlite3.Error):
            changed=True
        if changed:errors.append({'code':'schema_changed','message':'Schema changed or became unavailable after inspection. Start a new run.'})
        return {'validation_errors':errors,'uncertainties':uncertain,'schema_changed':changed,
                'review_status':'blocked' if errors or uncertain else 'approved',
                'events':event(state,'approval_gate','Revalidated reviewed proposal and schema fingerprints',errors=errors,uncertainties=uncertain)}
    def finalize(state):
        decision=state['review_decision']
        plan=MigrationPlan(**state['proposed_plan'],run_id=state['run_id'],
            source_schema_sha256=digest(state['source_schema']),destination_schema_sha256=digest(state['destination_schema']),
            approval={'reviewer':decision['reviewer'],'reason':decision['reason'],'approved_at':datetime.now(timezone.utc).isoformat()},
            mapping_origin=state['mapping_origin'],limitations=[
                'Planning only. No records transferred or post-migration checks executed.',
                'Schema validation cannot prove semantic correctness, actual NULL frequency, value ranges, ID collisions, unique conflicts or destination capacity.',
                'Synthetic examples are not observed data. Transfer engine must perform independent preflight checks.',
                'v1 supports one-to-one table mappings and preserved IDs. Joins, splits, merges, regenerated IDs, views and virtual tables require an extended contract.'])
        return {'final_plan':plan.model_dump(),'events':event(state,'finalize','Emitted approved MigrationPlan; databases unchanged')}
    def reject(state):
        return {'review_status':'rejected','final_plan':None,'events':event(state,'reject','Plan rejected; no final plan emitted')}
    graph=StateGraph(PlannerState)
    for name,node in [('inspect',inspect),('propose',propose),('validate',validate),('flag_review',assess),('human_review',human_review),('approval_gate',gate),('finalize',finalize),('reject',reject)]:graph.add_node(name,node)
    graph.add_edge(START,'inspect');graph.add_edge('inspect','propose');graph.add_edge('propose','validate')
    graph.add_conditional_edges('validate',lambda s:'flag_review' if s['validation_errors'] or s['uncertainties'] else 'human_review')
    graph.add_edge('flag_review','human_review')
    graph.add_conditional_edges('human_review',lambda s:{'edit':'validate','reject':'reject','approve':'approval_gate'}.get(s['review_status'],'human_review'))
    graph.add_conditional_edges('approval_gate',lambda s:'finalize' if s['review_status']=='approved' else 'human_review')
    graph.add_edge('finalize',END);graph.add_edge('reject',END)
    return graph.compile(checkpointer=checkpointer)
