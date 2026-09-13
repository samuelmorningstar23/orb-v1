"""Replay forecasts for the dashboard: out/tyreformer/live/2026_<event>.parquet plus a signed manifest.

Protocol of the exported numbers: the 2026 'rolling' experiment (tyreformer.train), i.e. each race is forecast by a model
trained on 2023-2025 plus only the 2026 races held before it; the race itself never enters training. Bands are the
conformal 90 % bands (margins from the 2023-2025 cross-validation). One row per origin (driver, lap) of the race.

CLI:  python -m tyreformer.export [--source rolling_ensemble]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from tyreformer import OUT
from tyreformer.train import PRED

LIVE = OUT / 'live'
KEEP_Q = ('q05', 'q25', 'q50', 'q75', 'q95')


def export(source: str, margins: dict[str, float], protocol: str, model_label: str = 'Orb TyreFormer') -> dict:
    P = pd.read_parquet(PRED / f'{source}.parquet')
    P = P[(P['season'] == 2026) & (P['session'] == 'R')]
    LIVE.mkdir(parents=True, exist_ok=True)
    files = {}
    for ev, g in P.groupby('event'):
        cols = ['driver', 'lap', 'stint', 'compound', 'age', 'n_obs', 'anchor', 'cliff_p3', 'cliff_p5']
        out = g[cols].copy()
        for h in range(1, 11):
            for q in KEEP_Q:
                out[f'h{h}_{q}'] = g[f'h{h}_{q}']
            c = margins.get(f'h{h}', 0.0)
            out[f'h{h}_lo90'] = g[f'h{h}_q05'] - c
            out[f'h{h}_hi90'] = g[f'h{h}_q95'] + c
        for hh in (3, 5):
            c = margins.get(f'cum{hh}', 0.0)
            out[f'cum{hh}_q50'] = g[f'cum{hh}_q50']
            out[f'cum{hh}_lo90'] = g[f'cum{hh}_q05'] - c
            out[f'cum{hh}_hi90'] = g[f'cum{hh}_q95'] + c
        p = LIVE / f'2026_{ev}.parquet'
        out.sort_values(['driver', 'lap']).to_parquet(p, index=False)
        files[p.name] = dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), rows=int(len(out)), drivers=int(out['driver'].nunique()))
    manifest = dict(model=model_label, source=source, protocol=protocol, conformal_margins=margins, generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                    units='seconds of corrected lap time (lap_s - 0.03 x 70 x (1 - (lap - 1) / n_laps))', uses_future_data=False, files=files)
    (LIVE / 'manifest.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default='rolling_ensemble')
    ap.add_argument('--margins', default=str(OUT / 'conformal_margins.json'))
    a = ap.parse_args(argv)
    margins = json.loads(Path(a.margins).read_text(encoding='utf-8'))
    m = export(a.source, margins, protocol='2026 rolling: each race forecast by a model trained on 2023-2025 and the earlier 2026 races only')
    print(f"exported {len(m['files'])} races to {LIVE}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
