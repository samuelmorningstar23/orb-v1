"""The run.py CLI: one scenario writes the artefacts with verifiable sidecars; the lattice reports timing."""
from __future__ import annotations

import json

import pandas as pd

from counterfactual.run import main
from schemas.lock_v2 import CounterfactualScenario
from shared.lockio import verify_sidecar


def test_cli_scenario_writes_artefacts(monza_csv, v2_lock, tmp_path, capsys):
    rc = main(['--event', 'Monza', '--driver', 'NOR', '--lap', '24', '--to', 'MEDIUM', '--set', 'NEW', '--mode', 'fixed_context', '--out', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'M-H -> M-H-M' in out and 'compile' in out
    d = tmp_path / 'monza_nor_lap24_to_medium_new_fixed_context'
    assert (d / 'laps.csv').exists() and (d / 'summary.json').exists() and (d / 'lap_deltas.json').exists() and (d / 'ghost_replay.json').exists()
    s = json.loads((d / 'summary.json').read_text(encoding='utf-8'))
    CounterfactualScenario.model_validate(s['scenario'])
    assert s['scenario']['forecast_hash'] == v2_lock['shared']['forecast_hash']
    for ref in s['scenario']['assets'].values():
        assert verify_sidecar(ref, s['sidecar_root'])[0] == 'ok'
    t = pd.read_csv(d / 'laps.csv')
    assert len(t) == 53 and t['lap'].iloc[-1] == 53


def test_reference_validator_accepts_cli_output(monza_csv, v2_lock, tmp_path):
    """validators/validate_lock.py (the reference validator) accepts a lock carrying the scenario written by the CLI, sidecars verified."""
    from validators.validate_lock import validate, EXIT_OK
    rc = main(['--event', 'Monza', '--driver', 'NOR', '--lap', '24', '--to', 'MEDIUM', '--mode', 'tyre_only', '--out', str(tmp_path), '--quiet'])
    assert rc == 0
    s = json.loads((tmp_path / 'monza_nor_lap24_to_medium_new_tyre_only' / 'summary.json').read_text(encoding='utf-8'))
    lock = dict(v2_lock)
    lock['counterfactuals'] = [s['scenario']]
    lock_path = tmp_path / 'lock_with_counterfactual.json'
    lock_path.write_text(json.dumps(lock), encoding='utf-8')
    assert validate(lock_path, root=tmp_path, strict=False, quiet=True) == EXIT_OK


def test_cli_frozen_field_refused(monza_csv, tmp_path, capsys):
    rc = main(['--event', 'Monza', '--driver', 'NOR', '--lap', '24', '--to', 'MEDIUM', '--mode', 'frozen_field', '--out', str(tmp_path)])
    assert rc == 2 and 'not available' in capsys.readouterr().err


def test_cli_lattice(monza_csv, tmp_path, capsys):
    rc = main(['--event', 'Monza', '--lattice', '--drivers', 'NOR,PIA', '--laps', '12,24,36', '--compounds', 'MEDIUM,SOFT', '--out', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '12 scenarios' in out and 'per scenario' in out
    rows = pd.read_csv(tmp_path / 'lattice_Monza_fixed_context.csv')
    meta = json.loads((tmp_path / 'lattice_Monza_fixed_context.json').read_text())
    assert len(rows) == 12 and meta['timing']['n_scenarios'] == 12 and meta['timing']['per_scenario_ms_max'] < 250
