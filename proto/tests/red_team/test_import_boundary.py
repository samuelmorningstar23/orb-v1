"""Import boundary (roadmap v5 task 0.0, Phase 0 acceptance 1 and 2).

Static: app_v2 pages / ui / state import no estimator or Ghost module directly (they consume app_v2/services only);
live/ and decision/ import nothing from counterfactual/, evaluation/, replay/, events/ or interaction/;
counterfactual/, events/ and replay/ import nothing from live/ or decision/.
Dynamic: in a fresh interpreter the Ghost core loads without any live module and the live core without any Ghost module.
Self-test: a planted violation in a temp tree is flagged, so an empty violation list means the scan looked."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parents[2]

ESTIMATOR_MODULES = ('live', 'decision', 'counterfactual', 'model_v2', 'pipeline', 'strategy2', 'liquid', 'evaluation', 'events', 'interaction', 'replay')
GHOST_SIDE = ('counterfactual', 'evaluation', 'replay', 'events', 'interaction', 'ghost')
LIVE_SIDE = ('live', 'decision')

RULES = [   # (label, directories to scan, forbidden top-level packages, paths exempt from the rule)
    ('app_v2 pages/ui/state consume services only', ('app_v2/pages', 'app_v2/ui', 'app_v2/state', 'app_v2/streamlit_app.py'), ESTIMATOR_MODULES, ()),
    ('app_v2 components: only the Race Twin player may touch replay/ (Workstream 4 rendering, no estimator)', ('app_v2/components',), tuple(m for m in ESTIMATOR_MODULES if m != 'replay'), ()),
    ('live/ and decision/ never import the Ghost side', ('live', 'decision'), GHOST_SIDE, ()),
    ('counterfactual/, events/, replay/ never import the live side', ('counterfactual', 'events', 'replay'), LIVE_SIDE, ()),
]


def imported_roots(path: Path) -> list[tuple[str, int]]:
    """Top-level package of every import statement in a module (absolute imports only), with line numbers."""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name.split('.')[0], node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module.split('.')[0], node.lineno))
    return out


def scan(root: Path, dirs: tuple[str, ...], forbidden: tuple[str, ...], exempt: tuple[str, ...] = ()) -> list[str]:
    violations = []
    for d in dirs:
        base = root / d
        files = [base] if base.is_file() else sorted(base.rglob('*.py')) if base.is_dir() else []
        for f in files:
            rel = f.relative_to(root).as_posix()
            if any(rel.startswith(e) for e in exempt):
                continue
            for mod, line in imported_roots(f):
                if mod in forbidden:
                    violations.append(f'{rel}:{line} imports {mod}')
    return violations


@pytest.mark.parametrize('label,dirs,forbidden,exempt', RULES, ids=[r[0][:40] for r in RULES])
def test_static_import_boundary(label, dirs, forbidden, exempt):
    missing = [d for d in dirs if not (PROTO / d).exists()]
    assert not missing, f'{label}: directories missing {missing}'
    v = scan(PROTO, dirs, forbidden, exempt)
    assert not v, f'{label}: forbidden imports\n  ' + '\n  '.join(v)


def test_scan_flags_a_planted_violation(tmp_path):
    """Self-test: the scanner must see a page that imports an estimator directly."""
    pages = tmp_path / 'app_v2' / 'pages'
    pages.mkdir(parents=True)
    (pages / 'sneaky.py').write_text('import streamlit as st\nfrom live.estimator import LiveTyreStateEstimator\nimport counterfactual.engine\n')
    (pages / 'clean.py').write_text('from app_v2.services import view_models as VM\n')
    v = scan(tmp_path, ('app_v2/pages',), ESTIMATOR_MODULES)
    assert v == ['app_v2/pages/sneaky.py:2 imports live', 'app_v2/pages/sneaky.py:3 imports counterfactual'], v


def _fresh_import(imports: str, must_not_load: tuple[str, ...]) -> list[str]:
    code = (f"import sys; sys.path.insert(0, {str(PROTO)!r}); {imports}; "
            f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {must_not_load!r}); print('\\n'.join(bad))")
    res = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120, cwd=str(PROTO))
    assert res.returncode == 0, res.stderr[-2000:]
    return [l for l in res.stdout.splitlines() if l]


def test_ghost_core_loads_without_live_modules():
    """Phase 0 acceptance 1: Ghost works without LiveTyreStateEstimator."""
    loaded = _fresh_import('import counterfactual.engine, counterfactual.provider, events', LIVE_SIDE)
    assert not loaded, f'importing the Ghost core loaded live-side modules: {loaded}'


def test_live_core_loads_without_ghost_modules():
    """Phase 0 acceptance 2: Live works without GhostStrategyEngine."""
    loaded = _fresh_import('import live.session, live.estimator, decision.optimizer', ('counterfactual', 'events', 'replay', 'interaction'))
    assert not loaded, f'importing the live core loaded Ghost-side modules: {loaded}'


def test_fresh_import_check_sees_a_deliberate_load():
    """Self-test: the closure check must report a module that is imported on purpose."""
    loaded = _fresh_import('import live.priors; import counterfactual.provider', LIVE_SIDE)
    assert 'live' in loaded and 'live.priors' in loaded, loaded
