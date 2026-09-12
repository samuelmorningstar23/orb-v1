"""Minimal lock v2 contract (C0 fixture). Workstream 1 extends it; stable blocks forbid extra properties; 'extensions' is free."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal
class Strict(BaseModel): model_config = ConfigDict(extra='forbid')
class Shared(Strict):
    schema_version: str; generated_at: str; forecast_hash: str; model_version: str; training_cutoff: str; support_definition: dict = Field(default_factory=dict)
class LivePredictor(Strict):
    data_cutoff: str; uses_future_data: Literal[False] = False; uses_post_race_reference: Literal[False] = False
    prior: dict = Field(default_factory=dict); posterior: dict = Field(default_factory=dict); recommendations: list = Field(default_factory=list); driver_feedback: list = Field(default_factory=list)
class GhostStrategy(Strict):
    mode: Literal['historical_audit', 'scenario_explorer', 'generalisation_scorecard']; event: str; driver: str; weather_context: str; forecast_snapshot_hash: str; model_implied: Literal[True] = True
    race_reference: dict = Field(default_factory=dict); counterfactual: dict = Field(default_factory=dict); generalisation_status: dict = Field(default_factory=dict)
class LockV2(Strict):
    shared: Shared; live_predictor: Optional[LivePredictor] = None; ghost_strategy: Optional[GhostStrategy] = None; extensions: dict = Field(default_factory=dict)
if __name__ == '__main__':
    import json, sys; L = LockV2.model_validate(json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'fixtures/lock_v2_fixture.json'))); print('fixture valid:', L.shared.forecast_hash)
