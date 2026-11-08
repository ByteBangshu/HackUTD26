"""Hand-authored model responses ONLY for tests. Never used by the runtime adapter."""
from planner.models import ProposedPlan

A={
 'patrons':('customers',{'patron_no':'id','display_name':'name'}),
 'menu':('products',{'sku':'id','label':'name','price_cents':'unit_cents'}),
 'checks':('orders',{'check_no':'id','patron_no':'customer_id','state':'status'}),
 'entries':('order_items',{'entry_no':'id','check_no':'order_id','sku':'product_id','qty':'quantity'})}
B={
 'guests_archive':('accounts',{'ref':'key','alias':'title'}),
 'dishes_archive':('catalog',{'code':'key','caption':'description','mass_grams':'mass_kg'}),
 'sales_archive':('tickets',{'number':'key','guest_ref':'account_key','gross_cents':'gross_dollars'}),
 'sold_archive':('ticket_rows',{'line':'key','sale_number':'ticket_key','dish_code':'catalog_key','portions':'units'})}

def fixture_plan(pair,source):
    mapping=A if pair=='a' else B
    tables=[]
    for s,(d,fields) in mapping.items():
        fs=[]
        for a,b in fields.items():
            trans={'kind':'rename','explanation':'Same business field per supplied synthetic data dictionary.'}
            if pair=='a' and a=='state':trans={'kind':'enum_translate','value_map':{'P':'paid','O':'open','V':'void'},'explanation':'Status translation supplied in synthetic data dictionary.'}
            if pair=='b' and a=='mass_grams':trans={'kind':'unit_scale','factor':'0.001','from_unit':'grams','to_unit':'kilograms','explanation':'Factor explicitly supplied by human context.'}
            if pair=='b' and a=='gross_cents':trans={'kind':'unit_scale','factor':'0.01','from_unit':'USD cents','to_unit':'USD dollars','explanation':'Factor explicitly supplied by human context.'}
            fs.append({'source_column':a,'destination_column':b,'transformation':trans,'status':'supported','confidence':.95,
                       'explanation':'Synthetic test response supported by supplied dictionary; not an LLM execution.',
                       'evidence':[f'source:{s}.{a}',f'destination:{d}.{b}']})
        tables.append({'source_table':s,'destination_table':d,'explanation':'Synthetic dictionary correspondence.','fields':fs})
    relations=[]
    for s,table in source['tables'].items():
        for fk in table['foreign_keys']:
            parent=fk['parent_table'];d,fields=mapping[s];dp,pfields=mapping[parent]
            relations.append({'source_child_table':s,'source_child_columns':fk['columns'],'source_parent_table':parent,'source_parent_columns':fk['parent_columns'],
                'destination_child_table':d,'destination_child_columns':[fields[c] for c in fk['columns']],
                'destination_parent_table':dp,'destination_parent_columns':[pfields[c] for c in fk['parent_columns']],
                'strategy':'preserve_ids','explanation':'Preserve declared FK through mapped ID columns.'})
    return ProposedPlan(table_mappings=tables,relationships=relations,unresolved_fields=[],assumptions=['Human reviewer must confirm the synthetic data dictionary.'],explanation='Hand-authored test fixture; not AI-generated.')

class FixtureAdapter:
    origin='test_fixture'
    def __init__(self,pair='a',mutation=None):self.pair=pair;self.mutation=mutation;self.calls=0
    def propose(self,source,destination,context):
        self.calls+=1
        p=fixture_plan(self.pair,source)
        if self.mutation:self.mutation(p)
        return p
