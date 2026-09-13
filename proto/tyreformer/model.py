"""Orb TyreFormer network: a small pre-norm transformer over the driver's last W laps plus one context token.

Inputs   tokens [B, W, F_tok] (one per lap, padded on the left), tok_mask [B, W] (True = real lap),
         context [B, F_ctx] (stint, compound, Pirelli C-number, season, weather, the weekend's pre-race forecast),
         circuit [B] (index into the circuit vocabulary; index 0 = unknown, used for unseen circuits and as dropout)
Outputs  q      [B, H, Q]  quantiles of y(k+h) - anchor, monotone in Q by construction
         cum    [B, 2, Q]  quantiles of the 3- and 5-lap sums of the same targets
         cliff  [B, 2]     logits of a realised cliff within 3 and 5 laps
The anchor is the mean corrected time of the state's last (up to) three kept laps, so every output is a lap-time
change relative to what the car is doing now.
"""
from __future__ import annotations

import torch
from torch import nn
import torch.nn.functional as F

QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
MID = QUANTILES.index(0.50)


def monotone_quantiles(raw: torch.Tensor) -> torch.Tensor:
    """raw [..., Q] -> quantiles: the median is free, the gaps outward from it are softplus-positive and cumulative."""
    mid = raw[..., MID:MID + 1]
    below = torch.cumsum(F.softplus(raw[..., :MID].flip(-1)), dim=-1).flip(-1)
    above = torch.cumsum(F.softplus(raw[..., MID + 1:]), dim=-1)
    return torch.cat([mid - below, mid, mid + above], dim=-1)


class TyreFormer(nn.Module):
    def __init__(self, n_tok: int, n_ctx: int, n_circuits: int, window: int = 24, horizons: int = 10, d: int = 96, layers: int = 3, heads: int = 4,
                 dropout: float = 0.1, circuit_dropout: float = 0.15):
        super().__init__()
        self.window, self.horizons, self.nq = window, horizons, len(QUANTILES)
        self.circuit_dropout = circuit_dropout
        self.tok_in = nn.Sequential(nn.Linear(n_tok, d), nn.GELU(), nn.Linear(d, d))
        self.ctx_in = nn.Sequential(nn.Linear(n_ctx, d), nn.GELU(), nn.Linear(d, d))
        self.circuit = nn.Embedding(n_circuits, d)
        self.pos = nn.Parameter(torch.zeros(1, window + 1, d))
        nn.init.normal_(self.pos, std=0.02)
        layer = nn.TransformerEncoderLayer(d, heads, 4 * d, dropout, activation='gelu', batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d)
        self.trunk = nn.Sequential(nn.Linear(2 * d + n_ctx, 2 * d), nn.GELU(), nn.Dropout(dropout), nn.Linear(2 * d, 2 * d), nn.GELU())
        self.head_q = nn.Linear(2 * d, horizons * self.nq)
        self.head_cum = nn.Linear(2 * d, 2 * self.nq)
        self.head_cliff = nn.Linear(2 * d, 2)

    def forward(self, tokens: torch.Tensor, tok_mask: torch.Tensor, context: torch.Tensor, circuit: torch.Tensor) -> dict[str, torch.Tensor]:
        B = tokens.shape[0]
        if self.training and self.circuit_dropout > 0:
            drop = torch.rand(B, device=circuit.device) < self.circuit_dropout
            circuit = torch.where(drop, torch.zeros_like(circuit), circuit)
        ctx = self.ctx_in(context) + self.circuit(circuit)
        x = torch.cat([ctx[:, None, :], self.tok_in(tokens)], dim=1) + self.pos
        pad = torch.cat([torch.zeros(B, 1, dtype=torch.bool, device=tokens.device), ~tok_mask], dim=1)
        h = self.norm(self.encoder(x, src_key_padding_mask=pad))
        z = self.trunk(torch.cat([h[:, 0], h[:, -1], context], dim=-1))
        q = monotone_quantiles(self.head_q(z).view(B, self.horizons, self.nq))
        cum = monotone_quantiles(self.head_cum(z).view(B, 2, self.nq))
        return dict(q=q, cum=cum, cliff=self.head_cliff(z))


def pinball(pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor, weights: torch.Tensor | None = None) -> torch.Tensor:
    """pred [..., Q], target [...], mask [...] -> mean pinball loss over valid entries (optional per-entry weights, e.g. per horizon)."""
    qs = torch.tensor(QUANTILES, device=pred.device, dtype=pred.dtype)
    e = target[..., None] - pred
    loss = torch.maximum(qs * e, (qs - 1.0) * e).mean(-1)
    m = mask.to(pred.dtype)
    if weights is not None:
        m = m * weights
    return (loss * m).sum() / m.sum().clamp_min(1.0)


def masked_bce(logits: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    m = mask.to(logits.dtype)
    loss = F.binary_cross_entropy_with_logits(logits, target, reduction='none')
    return (loss * m).sum() / m.sum().clamp_min(1.0)


__all__ = ['TyreFormer', 'QUANTILES', 'MID', 'pinball', 'masked_bce', 'monotone_quantiles']
