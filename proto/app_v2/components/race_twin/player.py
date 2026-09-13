"""Race Twin browser player (roadmap v5 task 0.5 / 13.5).

    race_twin_player(frames, track, pitlane, height=520, ...)   -> renders the self-contained HTML player through
                                                                   streamlit.components.v1.html (no external assets, no network)
    player_html(...)                                            -> the HTML string (tests, perf harness, static export)
    load_assets(event, driver, scenario_id=None)                -> (Frames, TrackPath, PitLane) from proto/out/maps/<event>/
    assets_status(event)                                        -> {'status': 'ok' | 'refused' | 'missing', ...} for degraded states

`frames`, `track` and `pitlane` accept the replay dataclasses, the plain dicts they export, or file paths. Colours come from
the frozen tokens (proto/ui/tokens.py through app_v2.theme.tokens). The player is a canvas + requestAnimationFrame loop with
play/pause, 1x-10x, a lap scrubber, a time bar, keyboard shortcuts, time-gap readout, compound/age badges, 3D camera controls, recorded circuit geometry and the exact median
ghost frame set. Outcome uncertainty remains on the parent strategy cards; road width and elevation are schematic. It exposes
window.__orbTwin (fps, seek, play, pause, setSpeed) and data-fps on the root for the performance harness.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np

HERE = Path(__file__).resolve().parent
PROTO_ROOT = HERE.parents[2]
if str(PROTO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTO_ROOT))

from app_v2.theme.tokens import COLORS, COMPOUNDS, COMPOUND_GLYPH, FONT_STACK   # noqa: E402
from replay import io as rio                                                   # noqa: E402
from replay.geometry import TrackPath, PitLane                                 # noqa: E402
from replay.timewarp import Frames                                             # noqa: E402

TEMPLATE_PATH = HERE / 'player.html'
CONTROLS_HEIGHT = 128          # HUD rows + control bar, in CSS px; the canvas takes the rest of `height`


def _frames_dict(frames: Any) -> dict:
    if isinstance(frames, Frames):
        return frames.to_player_dict()
    if isinstance(frames, (str, Path)):
        return Frames.load(frames).to_player_dict()
    if isinstance(frames, dict) and 't' in frames:
        return frames
    raise TypeError('frames must be a replay.timewarp.Frames, its to_player_dict() output or a path to frames_*.npz')


def _track_dict(track: Any) -> dict:
    if isinstance(track, TrackPath):
        return track.to_dict()
    if isinstance(track, (str, Path)):
        p = Path(track); return TrackPath.load(p if p.is_dir() else p.parent).to_dict()
    if isinstance(track, dict) and 'x' in track:
        return track
    raise TypeError('track must be a replay.geometry.TrackPath, its to_dict() output or the maps directory')


def _pitlane_dict(pitlane: Any) -> Optional[dict]:
    if pitlane is None:
        return None
    if isinstance(pitlane, PitLane):
        return pitlane.to_dict()
    if isinstance(pitlane, (str, Path)):
        p = Path(pitlane); return PitLane.load(p if p.is_dir() else p.parent).to_dict()
    if isinstance(pitlane, dict) and 'x' in pitlane:
        return pitlane
    raise TypeError('pitlane must be a replay.geometry.PitLane, its to_dict() output, the maps directory or None')


def player_html(frames: Any, track: Any, pitlane: Any = None, height: int = 520, presentation: bool = False, autoplay: bool = False, speed: int = 1, start_t: float = 0.0,
                title: Optional[str] = None, show_fps: bool = True, stop_lap: Optional[int] = None) -> str:
    """Self-contained HTML for the player. `height` is the total component height in CSS px."""
    fr = _frames_dict(frames); tr = _track_dict(track); pl = _pitlane_dict(pitlane)
    payload = dict(frames=fr, track=tr, pitlane=pl, options=dict(total_height=int(height), canvas_height=max(int(height) - CONTROLS_HEIGHT, 160), presentation=bool(presentation), autoplay=bool(autoplay), speed=int(speed) if int(speed) in (1, 2, 5, 10) else 1,
                                                                 stop_lap=int(stop_lap) if stop_lap is not None else None, start_t=float(start_t), title=title or '', show_fps=bool(show_fps)),
                   colors=dict(bg=COLORS['background'], surface=COLORS['surface'], raised=COLORS['raised'], border=COLORS['border'], text=COLORS['text'], text2=COLORS['text_secondary'], live=COLORS['live'],
                               decision=COLORS['decision'], critical=COLORS['critical'], compounds=dict(COMPOUNDS, UNKNOWN=COLORS['text_secondary']), glyphs=dict(COMPOUND_GLYPH), font=FONT_STACK))
    data = json.dumps(payload, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    html = TEMPLATE_PATH.read_text(encoding='utf-8').replace('/*__ORB_SCENE__*/', (TEMPLATE_PATH.parent / 'scene3d.js').read_text(encoding='utf-8'))
    for k, v in dict(__BG__=COLORS['background'], __SURFACE__=COLORS['surface'], __RAISED__=COLORS['raised'], __BORDER__=COLORS['border'], __TEXT__=COLORS['text'], __TEXT2__=COLORS['text_secondary'],
                     __LIVE__=COLORS['live'], __DECISION__=COLORS['decision'], __CRITICAL__=COLORS['critical'], __FONT__=FONT_STACK).items():
        html = html.replace(k, v)
    return html.replace('/*__ORB_DATA__*/null', data)


def race_twin_player(frames: Any, track: Any, pitlane: Any = None, height: int = 520, presentation: bool = False, autoplay: bool = False, speed: int = 1, start_t: float = 0.0,
                     title: Optional[str] = None, show_fps: bool = True, key: Optional[str] = None, stop_lap: Optional[int] = None) -> None:
    """Streamlit entry point. Renders the player in an iframe of `height` px; the map fills the width of the container.
    `key` is accepted for call-site symmetry with other components (components.html has no key; it is unused)."""
    import streamlit.components.v1 as components
    components.html(player_html(frames, track, pitlane, height=height, presentation=presentation, autoplay=autoplay, speed=speed, start_t=start_t, title=title, show_fps=show_fps, stop_lap=stop_lap),
                    height=int(height), scrolling=False)


# ---------------------------------------------------------------- assets

def maps_dir(event: str, root: Optional[str | Path] = None) -> Path:
    return rio.event_dir(event, root)


def assets_status(event: str, root: Optional[str | Path] = None) -> dict:
    """'ok' with the driver/frames lists, 'refused' with the reason from meta.json, or 'missing'."""
    d = maps_dir(event, root)
    meta_p = d / 'meta.json'
    if not meta_p.exists():
        return dict(status='missing', event=event, reason=f'no maps built for {event} (run replay/build_maps.py)', dir=str(d))
    meta = rio.load_json(meta_p, verify_hash=False)
    status, msg = rio.verify(meta_p)
    if meta.get('status') == 'refused':
        return dict(status='refused', event=event, reason=meta.get('reason', 'position feed refused'), quality=meta.get('quality', {}), dir=str(d), sidecar=status)
    drivers = [k for k, v in (meta.get('drivers') or {}).items() if v.get('status') == 'ok']
    refused = {k: v.get('reason') for k, v in (meta.get('drivers') or {}).items() if v.get('status') != 'ok'}
    return dict(status='ok', event=event, dir=str(d), L=meta.get('L'), n_points=meta.get('n_points'), drivers=drivers, refused_drivers=refused, frames=meta.get('frames', []),
                pitlane=meta.get('pitlane', {}), quality=meta.get('quality', {}), sidecar=status, identity_check=meta.get('identity_check'))


def list_frames(event: str, root: Optional[str | Path] = None) -> list[dict]:
    d = maps_dir(event, root)
    out = []
    for p in sorted(d.glob('frames_*.npz')):
        stem = p.stem[len('frames_'):]
        drv, _, sid = stem.partition('_')
        out.append(dict(driver=drv, scenario_id=sid, path=str(p), bytes=p.stat().st_size, sidecar=rio.verify(p)[0]))
    return out


def load_assets(event: str, driver: Optional[str] = None, scenario_id: Optional[str] = None, root: Optional[str | Path] = None) -> tuple[Optional[Frames], TrackPath, PitLane]:
    """(frames or None, track, pitlane). Frames: the requested scenario, else the first frames file of the driver."""
    d = maps_dir(event, root)
    track = TrackPath.load(d); pitlane = PitLane.load(d)
    frames = None
    if driver:
        cands = [f for f in list_frames(event, root) if f['driver'] == driver.upper() and (scenario_id is None or f['scenario_id'] == scenario_id)]
        if cands:
            frames = Frames.load(cands[0]['path'])
    return frames, track, pitlane


def load_track(event: str, root: Optional[str | Path] = None) -> TrackPath:
    """Circuit geometry alone, with no frame set loaded: the accessor a page uses when no scenario applies."""
    return TrackPath.load(maps_dir(event, root))


__all__ = ['race_twin_player', 'player_html', 'load_assets', 'load_track', 'list_frames', 'assets_status', 'maps_dir', 'CONTROLS_HEIGHT']


def static_track3d(track, height: int = 360) -> None:
    """Recorded circuit in a 3D camera, without invented car positions or replay frames."""
    import streamlit.components.v1 as components
    data = json.dumps(_track_dict(track), separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    js = (TEMPLATE_PATH.parent / 'scene3d.js').read_text(encoding='utf-8')
    html = '<style>body{margin:0;background:#0d1824;color:#b8cbd9;font:12px system-ui}canvas{width:100%;height:' + str(height-40) + 'px;cursor:grab;touch-action:none}button{background:#23394c;color:#ddedf6;border:1px solid #496275;border-radius:7px;padding:5px 12px;margin:4px}footer{display:flex;justify-content:space-between;align-items:center}</style><canvas aria-label="3D circuit geometry, no car positions"></canvas><footer><span>Recorded geometry · schematic elevation</span><button id="reset">Reset view</button></footer><script>' + js + '\nconst canvas=document.querySelector("canvas"),ctx=canvas.getContext("2d"),T=' + data + ';let scene;function draw(){const d=window.devicePixelRatio||1;canvas.width=canvas.clientWidth*d;canvas.height=canvas.clientHeight*d;scene.draw({},null)}scene=window.createOrbScene3D(canvas,ctx,T,null,{},draw);document.querySelector("#reset").onclick=()=>scene.reset();new ResizeObserver(draw).observe(canvas);draw();</script>'
    components.html(html, height=height, scrolling=False)
