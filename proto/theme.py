"""Shared visual system: Barlow Condensed (display) + Georgia (text), dark editorial palette."""
import matplotlib, os
from matplotlib import font_manager as fm
HERE = os.path.dirname(os.path.abspath(__file__))
for f in ['BarlowCondensed-Bold.ttf', 'BarlowCondensed-SemiBold.ttf']:
    p = os.path.join(HERE, 'fonts', f)
    if os.path.exists(p): fm.fontManager.addfont(p)
for f in ['Georgia.ttf', 'Georgia Bold.ttf', 'Georgia Italic.ttf']:
    p = '/System/Library/Fonts/Supplemental/' + f
    if os.path.exists(p): fm.fontManager.addfont(p)
DISPLAY, TEXT = 'Barlow Condensed', 'Georgia'
BG, INK, MUTED, RED, GOLD, SLATE, PANEL, ROSE, LINE = '#0E1013', '#ECEDEF', '#9AA1AA', '#E10600', '#F2C230', '#8FB3D9', '#161A20', '#22161A', '#2B3038'
PAL = {'SOFT': RED, 'MEDIUM': GOLD, 'HARD': SLATE}
matplotlib.rcParams.update({
    'font.family': TEXT, 'text.color': INK, 'axes.labelcolor': MUTED, 'xtick.color': MUTED, 'ytick.color': MUTED,
    'figure.facecolor': BG, 'axes.facecolor': BG, 'savefig.facecolor': BG, 'axes.edgecolor': LINE, 'axes.grid': True,
    'grid.color': '#20242B', 'grid.linewidth': 0.6, 'axes.spines.top': False, 'axes.spines.right': False,
    'legend.labelcolor': INK, 'legend.frameon': False, 'axes.titlecolor': INK,
})
