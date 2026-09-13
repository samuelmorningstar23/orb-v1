"""Train Orb TyreFormer.

Experiments (sealed holdout weekends are never in any of these sets; tyreformer.data refuses to load them):
    cv          5-fold cross-validation grouped by weekend on the 2023-2025 development weekends -> out-of-fold predictions
                (model selection and conformal calibration only)
    temporal    trained on every 2023-2025 development weekend, predicts every 2026 race: a season the model never saw,
                after a regulation change (the headline test against the Orb v1 estimator)
    rolling     2026 in calendar order: each race forecast by a model trained on 2023-2025 plus the earlier 2026 races only
    production  trained on every development weekend of 2023-2026 (the model the dashboard and Madrid would use)
Early stopping uses an inner validation split of whole weekends drawn from the training weekends only.

CLI:  python -m tyreformer.train --experiment cv|temporal|production [--seeds 3] [--epochs 40]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import torch

from tyreformer import OUT
from tyreformer.data import SampleSet, CACHE, TOKEN_FEATURES, CONTEXT_FEATURES, W, H, circuits
from tyreformer.model import TyreFormer, QUANTILES, MID, pinball, masked_bce

MODELS = OUT / 'models'
PRED = OUT / 'predictions'


@dataclass
class Config:
    d: int = 96
    layers: int = 3
    heads: int = 4
    dropout: float = 0.10
    circuit_dropout: float = 0.15
    lr: float = 2e-3
    weight_decay: float = 0.05
    batch: int = 1024
    epochs: int = 40
    patience: int = 6
    warmup_steps: int = 150
    w_cum: float = 0.25
    w_cliff: float = 0.5
    target_clip: tuple[float, float] = (-6.0, 12.0)
    cum_clip: tuple[float, float] = (-20.0, 40.0)
    val_weekends: float = 0.12
    tok_noise: float = 0.0
    horizon_weighting: str = 'uniform'      # 'uniform' | 'inv_sqrt' (weight 1/sqrt(h): the near horizons the product scores)


def device() -> torch.device:
    return torch.device('mps') if torch.backends.mps.is_available() else torch.device('cpu')


def to_tensors(S: SampleSet, dev: torch.device, cfg: Config) -> dict[str, torch.Tensor]:
    return dict(tokens=torch.from_numpy(S.tokens).to(dev), tok_mask=torch.from_numpy(S.tok_mask).to(dev), context=torch.from_numpy(S.context).to(dev),
                circuit=torch.from_numpy(S.circuit).to(dev), target=torch.from_numpy(np.clip(S.target, *cfg.target_clip)).to(dev),
                target_mask=torch.from_numpy(S.target_mask).to(dev), cum=torch.from_numpy(np.clip(S.cum, *cfg.cum_clip)).to(dev), cum_mask=torch.from_numpy(S.cum_mask).to(dev),
                cliff=torch.from_numpy(S.cliff).to(dev), cliff_mask=torch.from_numpy(S.cliff_mask).to(dev))


def batch_loss(model: TyreFormer, T: dict[str, torch.Tensor], idx: torch.Tensor, cfg: Config) -> tuple[torch.Tensor, dict[str, float]]:
    out = model(T['tokens'][idx], T['tok_mask'][idx], T['context'][idx], T['circuit'][idx])
    hw = None
    if cfg.horizon_weighting == 'inv_sqrt':
        hw = (1.0 / torch.sqrt(torch.arange(1, out['q'].shape[1] + 1, device=out['q'].device, dtype=out['q'].dtype)))[None, :]
    lq = pinball(out['q'], T['target'][idx], T['target_mask'][idx], hw)
    lc = pinball(out['cum'], T['cum'][idx], T['cum_mask'][idx])
    lb = masked_bce(out['cliff'], T['cliff'][idx], T['cliff_mask'][idx])
    loss = lq + cfg.w_cum * lc + cfg.w_cliff * lb
    return loss, dict(q=float(lq.detach()), cum=float(lc.detach()), cliff=float(lb.detach()))


@torch.no_grad()
def evaluate_loss(model: TyreFormer, T: dict[str, torch.Tensor], cfg: Config) -> float:
    model.eval()
    n = T['tokens'].shape[0]
    tot, cnt = 0.0, 0
    for s in range(0, n, 4096):
        idx = torch.arange(s, min(n, s + 4096), device=T['tokens'].device)
        loss, _ = batch_loss(model, T, idx, cfg)
        tot += float(loss) * len(idx)
        cnt += len(idx)
    return tot / max(cnt, 1)


def split_weekends(race_ids: np.ndarray, frac: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Boolean masks (train, val) holding out whole weekends."""
    u = np.array(sorted(set(race_ids)))
    rng = np.random.default_rng(seed)
    n_val = max(1, int(round(frac * len(u))))
    val = set(rng.choice(u, n_val, replace=False))
    m = np.array([r in val for r in race_ids])
    return ~m, m


def train_model(S_train: SampleSet, cfg: Config, seed: int, quiet: bool = False, S_val: Optional[SampleSet] = None) -> tuple[TyreFormer, dict[str, Any]]:
    dev = device()
    torch.manual_seed(seed)
    np.random.seed(seed)
    if S_val is None:
        tr_m, va_m = split_weekends(S_train.meta['race_id'].to_numpy(), cfg.val_weekends, seed)
        S_val, S_tr = S_train.subset(va_m), S_train.subset(tr_m)
    else:
        S_tr = S_train
    n_circ = len(circuits(extra=('Madrid',)))
    model = TyreFormer(len(TOKEN_FEATURES), len(CONTEXT_FEATURES), n_circ, W, H, cfg.d, cfg.layers, cfg.heads, cfg.dropout, cfg.circuit_dropout).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    Ttr, Tva = to_tensors(S_tr, dev, cfg), to_tensors(S_val, dev, cfg)
    n = len(S_tr)
    steps_per_epoch = math.ceil(n / cfg.batch)
    total = steps_per_epoch * cfg.epochs
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / cfg.warmup_steps) * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * min(s, total) / total))))
    best, best_state, bad, hist = float('inf'), None, 0, []
    t0 = time.time()
    for ep in range(cfg.epochs):
        model.train()
        perm = torch.randperm(n, device=dev)
        parts = dict(q=0.0, cum=0.0, cliff=0.0)
        for s in range(0, n, cfg.batch):
            idx = perm[s:s + cfg.batch]
            loss, p = batch_loss(model, Ttr, idx, cfg)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            for k in parts:
                parts[k] += p[k] * len(idx) / n
        vl = evaluate_loss(model, Tva, cfg)
        hist.append(dict(epoch=ep + 1, train=parts, val=vl, seconds=round(time.time() - t0, 1)))
        if not quiet:
            print(f'  epoch {ep + 1:2d}: train q {parts["q"]:.4f} cum {parts["cum"]:.4f} cliff {parts["cliff"]:.4f} | val {vl:.4f} ({time.time() - t0:.0f} s)', flush=True)
        if vl < best - 1e-4:
            best, bad = vl, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= cfg.patience:
                break
    model.load_state_dict(best_state)
    model.to(dev)
    return model, dict(history=hist, best_val=best, epochs_run=len(hist), n_train=int(n), n_val=int(len(S_val)), train_weekends=int(S_tr.meta['race_id'].nunique()),
                       val_weekends=sorted(S_val.meta['race_id'].unique().tolist()), seconds=round(time.time() - t0, 1))


@torch.no_grad()
def predict(models: list[TyreFormer], S: SampleSet) -> dict[str, np.ndarray]:
    """Ensemble mean of quantiles (re-sorted) and of cliff probabilities."""
    dev = device()
    cfg = Config()
    T = to_tensors(S, dev, cfg)
    n = len(S)
    qs, cums, cls = [], [], []
    for m in models:
        m.eval()
        q_all, c_all, l_all = [], [], []
        for s in range(0, n, 4096):
            idx = torch.arange(s, min(n, s + 4096), device=dev)
            out = m(T['tokens'][idx], T['tok_mask'][idx], T['context'][idx], T['circuit'][idx])
            q_all.append(out['q'].cpu()); c_all.append(out['cum'].cpu()); l_all.append(torch.sigmoid(out['cliff']).cpu())
        qs.append(torch.cat(q_all).numpy()); cums.append(torch.cat(c_all).numpy()); cls.append(torch.cat(l_all).numpy())
    q = np.sort(np.mean(qs, axis=0), axis=-1)
    cum = np.sort(np.mean(cums, axis=0), axis=-1)
    return dict(q=q, cum=cum, cliff=np.mean(cls, axis=0))


def predictions_frame(S: SampleSet, P: dict[str, np.ndarray], tag: str) -> pd.DataFrame:
    """One row per origin: meta, anchor, absolute quantile forecasts of y(k+h), cumulative sums, cliff probabilities."""
    df = S.meta.copy()
    df['anchor'] = S.anchor
    for h in range(H):
        for j, q in enumerate(QUANTILES):
            df[f'h{h + 1}_q{int(round(q * 100)):02d}'] = S.anchor + P['q'][:, h, j]
    for i, hh in enumerate((3, 5)):
        for j, q in enumerate(QUANTILES):
            df[f'cum{hh}_q{int(round(q * 100)):02d}'] = hh * S.anchor + P['cum'][:, i, j]
    df['cliff_p3'] = P['cliff'][:, 0]
    df['cliff_p5'] = P['cliff'][:, 1]
    df['model'] = tag
    return df


def save_models(models: list[TyreFormer], cfg: Config, info: dict[str, Any], name: str) -> Path:
    MODELS.mkdir(parents=True, exist_ok=True)
    p = MODELS / f'{name}.pt'
    torch.save(dict(states=[{k: v.cpu() for k, v in m.state_dict().items()} for m in models], config=asdict(cfg), token_features=list(TOKEN_FEATURES),
                    context_features=list(CONTEXT_FEATURES), window=W, horizons=H, quantiles=list(QUANTILES), circuits=circuits(extra=('Madrid',)), info=info), p)
    return p


def load_models(name: str) -> tuple[list[TyreFormer], dict[str, Any]]:
    blob = torch.load(MODELS / f'{name}.pt', map_location='cpu', weights_only=False)
    c = Config(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in blob['config'].items()})
    dev = device()
    models = []
    for st in blob['states']:
        m = TyreFormer(len(blob['token_features']), len(blob['context_features']), len(blob['circuits']), blob['window'], blob['horizons'], c.d, c.layers, c.heads, c.dropout, c.circuit_dropout)
        m.load_state_dict(st)
        models.append(m.to(dev).eval())
    return models, blob


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run(experiment: str, seeds: int, cfg: Config, quiet: bool = False, tag: str = '', samples: str = 'samples_dev.npz') -> dict[str, Any]:
    samples_path = CACHE / samples
    S = SampleSet.load(samples_path)
    PRED.mkdir(parents=True, exist_ok=True)
    season = S.meta['season'].to_numpy()
    t0 = time.time()
    report: dict[str, Any] = dict(experiment=experiment, config=asdict(cfg), seeds=seeds, samples=str(samples_path.name), samples_sha16=sha_of(samples_path), started=time.strftime('%Y-%m-%dT%H:%M:%S'))
    name = experiment + (f'_{tag}' if tag else '')
    if experiment == 'cv':
        dev_m = season <= 2025
        D = S.subset(dev_m)
        rids = np.array(sorted(D.meta['race_id'].unique()))
        rng = np.random.default_rng(2026)
        order = rng.permutation(rids)
        folds = {r: i % 5 for i, r in enumerate(order)}
        fold = D.meta['race_id'].map(folds).to_numpy()
        frames, infos = [], []
        for f in range(5):
            tr, te = D.subset(fold != f), D.subset(fold == f)
            models = []
            for sd in range(seeds):
                if not quiet:
                    print(f'fold {f} seed {sd}: train {len(tr)} / test {len(te)} origins', flush=True)
                m, info = train_model(tr, cfg, seed=100 * f + sd, quiet=quiet)
                models.append(m); infos.append(dict(fold=f, seed=sd, **{k: v for k, v in info.items() if k != 'history'}, history=info['history']))
            frames.append(predictions_frame(te, predict(models, te), f'tyreformer_cv_fold{f}'))
        out = pd.concat(frames, ignore_index=True)
        out.to_parquet(PRED / f'{name}.parquet', index=False)
        report.update(folds={str(k): int(v) for k, v in folds.items()}, runs=infos)
    elif experiment == 'temporal':
        tr, te = S.subset(season <= 2025), S.subset(season == 2026)
        models, infos = [], []
        for sd in range(seeds):
            m, info = train_model(tr, cfg, seed=7000 + sd, quiet=quiet)
            models.append(m); infos.append(info)
        out = predictions_frame(te, predict(models, te), 'tyreformer_temporal')
        out.to_parquet(PRED / f'{name}.parquet', index=False)
        save_models(models, cfg, dict(experiment='temporal', train='2023-2025 development weekends', runs=[{k: v for k, v in i.items() if k != 'history'} for i in infos]), name)
        report.update(runs=infos)
    elif experiment == 'rolling':
        # the deployment protocol inside 2026: race r is forecast by a model trained on 2023-2025 plus the 2026 races held
        # before r in the calendar (never r itself, never a later race)
        from evaluation import CALENDAR_2026
        ev26 = S.meta['event'].to_numpy()
        frames, infos = [], []
        for i, ev in enumerate(CALENDAR_2026):
            te_m = (season == 2026) & (ev26 == ev)
            if not te_m.any():
                continue
            earlier = set(CALENDAR_2026[:i])
            tr_m = (season <= 2025) | ((season == 2026) & np.isin(ev26, list(earlier)))
            tr, te = S.subset(tr_m), S.subset(te_m)
            models = []
            for sd in range(seeds):
                m, info = train_model(tr, cfg, seed=8000 + 10 * i + sd, quiet=quiet)
                models.append(m); infos.append(dict(event=ev, seed=sd, earlier_2026=sorted(earlier), **{k: v for k, v in info.items() if k != 'history'}))
            if not quiet:
                print(f'rolling {ev}: trained on {tr.meta["race_id"].nunique()} weekends ({len(earlier)} earlier 2026 races), {len(te)} origins', flush=True)
            frames.append(predictions_frame(te, predict(models, te), f'tyreformer_rolling_{ev}'))
        out = pd.concat(frames, ignore_index=True)
        out.to_parquet(PRED / f'{name}.parquet', index=False)
        report.update(runs=infos)
    elif experiment == 'production':
        models, infos = [], []
        for sd in range(seeds):
            m, info = train_model(S, cfg, seed=9000 + sd, quiet=quiet)
            models.append(m); infos.append(info)
        save_models(models, cfg, dict(experiment='production', train='2023-2026 development weekends', runs=[{k: v for k, v in i.items() if k != 'history'} for i in infos]), name)
        report.update(runs=infos)
    else:
        raise ValueError(experiment)
    report['seconds'] = round(time.time() - t0, 1)
    (OUT / 'logs').mkdir(parents=True, exist_ok=True)
    (OUT / 'logs' / f'train_{name}.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--experiment', required=True, choices=('cv', 'temporal', 'rolling', 'production'))
    ap.add_argument('--seeds', type=int, default=1)
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--d', type=int, default=96)
    ap.add_argument('--layers', type=int, default=3)
    ap.add_argument('--lr', type=float, default=2e-3)
    ap.add_argument('--dropout', type=float, default=0.10)
    ap.add_argument('--circuit-dropout', type=float, default=0.15)
    ap.add_argument('--weight-decay', type=float, default=0.05)
    ap.add_argument('--w-cliff', type=float, default=0.5)
    ap.add_argument('--w-cum', type=float, default=0.25)
    ap.add_argument('--patience', type=int, default=6)
    ap.add_argument('--batch', type=int, default=1024)
    ap.add_argument('--tok-noise', type=float, default=0.0)
    ap.add_argument('--horizon-weighting', default='uniform', choices=('uniform', 'inv_sqrt'))
    ap.add_argument('--tag', default='')
    ap.add_argument('--samples', default='samples_dev.npz')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    cfg = Config(epochs=a.epochs, d=a.d, layers=a.layers, lr=a.lr, dropout=a.dropout, circuit_dropout=a.circuit_dropout, weight_decay=a.weight_decay, w_cliff=a.w_cliff,
                 w_cum=a.w_cum, patience=a.patience, batch=a.batch, tok_noise=a.tok_noise, horizon_weighting=a.horizon_weighting)
    r = run(a.experiment, a.seeds, cfg, quiet=a.quiet, tag=a.tag, samples=a.samples)
    print(f"{a.experiment}{'_' + a.tag if a.tag else ''} done in {r['seconds']} s")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
