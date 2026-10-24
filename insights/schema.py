from typing import Literal

from pydantic import BaseModel

# No Field(min_length=...) etc. here on purpose: this model is also sent to
# Gemini as the response schema and the limits are enforced in validator.py.


class Claim(BaseModel):
    fact_id: str
    value: str


class Insight(BaseModel):
    statement: str
    kind: Literal["observation", "association"]
    claims: list[Claim]


class Investigation(BaseModel):
    action: str
    rationale: str
    fact_ids: list[str]


class Report(BaseModel):
    headline: str
    headline_fact_ids: list[str]
    insights: list[Insight]
    recommended_investigations: list[Investigation]
    limitations: list[str]
