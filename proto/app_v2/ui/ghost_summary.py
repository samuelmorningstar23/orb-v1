"""Plain-language description of a validated prepared Ghost strategy; no new forecast."""
from html import escape


def plan_text(plan):
    stints = plan.get('stints') or []
    if not stints:
        return 'Plan details unavailable'
    text = str(stints[0]['compound']).title()
    for stop, stint in zip(plan.get('pit_laps') or [], stints[1:]):
        text += f" → {str(stint['compound']).title()} after lap {int(stop)}"
    return text


def strategy_summary(sc):
    """The intervention is a hypothetical change, never an observed tyre change."""
    old = str(sc.from_compound).title() or 'Current tyre'
    new = str(sc.to_compound).title()
    actual_stops = len(sc.actual_plan.get('pit_laps') or [])
    ghost_stops = len(sc.cf_plan.get('pit_laps') or [])
    if ghost_stops > actual_stops:
        trade = 'This plan adds pit time in exchange for a different tyre stint.'
    elif ghost_stops < actual_stops:
        trade = 'This plan removes a stop, trading less pit time against longer tyre stints.'
    else:
        trade = 'This plan keeps the stop count and changes the timing or tyre choice.'
    delta = float(sc.finish_delta_s)
    result = (f'The model estimates a median {abs(delta):.1f} s gain.' if delta < -.05 else
              f'The model estimates a median {delta:.1f} s loss.' if delta > .05 else
              'The model estimates almost no change in finish time.')
    if sc.q10 <= 0 <= sc.q90:
        uncertainty = 'The outcome range spans both gain and loss, so the advantage is uncertain.'
    elif sc.q90 < 0:
        uncertainty = 'The central outcome range favours this plan, without guaranteeing a gain.'
    else:
        uncertainty = 'The central outcome range favours the original plan.'
    source = ('Frozen pre-race curves; model-implied scenario.' if sc.is_pre_race else
              'Historical reference curves excluding this driver.')
    return dict(title=f'After lap {sc.lap} · {old} → {sc.set_status} {new}',
                timing=f'The Ghost fits {sc.set_status} {new} tyres for lap {sc.lap + 1}.',
                actual=plan_text(sc.actual_plan), ghost=plan_text(sc.cf_plan),
                analysis=f'{trade} {result} {uncertainty}',
                model=f'Single-car tyre and pit-stop simulation. {source} Rivals do not react.')


def summary_html(sc):
    s = {k: escape(v) for k, v in strategy_summary(sc).items()}
    return (f'<section class="orb-strategy-summary" aria-label="Strategy at a glance">'
            f'<div class="orb-strategy-eyebrow">THE CHANGE YOU ARE TESTING</div>'
            f'<h3>{s["title"]}</h3><p>{s["timing"]} This is the simulated change.</p>'
            f'<div class="orb-strategy-plans"><div><span>Recorded plan</span><strong>{s["actual"]}</strong></div>'
            f'<div><span>Ghost plan</span><strong>{s["ghost"]}</strong></div></div>'
            f'<p class="orb-strategy-analysis">{s["analysis"]}</p>'
            f'<div class="orb-strategy-model">{s["model"]}</div></section>')
