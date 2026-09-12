"""Race Twin player. `race_twin_player` renders the canvas player; `plotly_fallback` animates the same frames with Plotly.

    from app_v2.components.race_twin import race_twin_player, load_assets, assets_status
    frames, track, pitlane = load_assets('Monza', 'NOR')          # proto/out/maps/Monza/
    race_twin_player(frames, track, pitlane, height=520)
"""
from app_v2.components.race_twin.player import race_twin_player, player_html, load_assets, list_frames, assets_status, maps_dir
from app_v2.components.race_twin.plotly_fallback import race_twin_map, race_twin_animation

__all__ = ['race_twin_player', 'player_html', 'load_assets', 'list_frames', 'assets_status', 'maps_dir', 'race_twin_map', 'race_twin_animation']
