from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)

class Transformation(StrictModel):
    kind: Literal['identity','rename','unit_scale','enum_translate','cast','constant']
    explanation: str = Field(min_length=1)
    factor: str | None = None
    from_unit: str | None = None
    to_unit: str | None = None
    value_map: dict[str,str] = Field(default_factory=dict)
    target_type: str | None = None
    constant: str | int | float | bool | None = None

class FieldMapping(StrictModel):
    source_column: str | None
    destination_column: str
    transformation: Transformation
    status: Literal['supported','needs_review']
    confidence: float = Field(ge=0,le=1)
    explanation: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)

class TableMapping(StrictModel):
    source_table: str
    destination_table: str
    explanation: str = Field(min_length=1)
    fields: list[FieldMapping]

class IDRelationship(StrictModel):
    source_child_table: str
    source_child_columns: list[str] = Field(min_length=1)
    source_parent_table: str
    source_parent_columns: list[str] = Field(min_length=1)
    destination_child_table: str
    destination_child_columns: list[str] = Field(min_length=1)
    destination_parent_table: str
    destination_parent_columns: list[str] = Field(min_length=1)
    strategy: Literal['preserve_ids','id_lookup']
    explanation: str = Field(min_length=1)

class UnresolvedField(StrictModel):
    side: Literal['source','destination']
    table: str
    column: str | None
    reason: str = Field(min_length=1)

class ProposedPlan(StrictModel):
    table_mappings: list[TableMapping]
    relationships: list[IDRelationship]
    unresolved_fields: list[UnresolvedField]
    assumptions: list[str]
    explanation: str = Field(min_length=1)

class Approval(StrictModel):
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    approved_at: str

class MigrationPlan(ProposedPlan):
    format_version: Literal['1.0'] = '1.0'
    run_id: str
    status: Literal['approved'] = 'approved'
    source_schema_sha256: str
    destination_schema_sha256: str
    approval: Approval
    mapping_origin: Literal['llm','test_fixture']
    limitations: list[str]

class ReviewDecision(StrictModel):
    action: Literal['approve','edit','reject']
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    plan: ProposedPlan | None = None
