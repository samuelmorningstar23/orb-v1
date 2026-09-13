"""Small hover/focus explanations for product terms. No numerical calculations."""
from app_v2.ui.formatting import esc

GLOSSARY = {
    'Tyre degradation': 'How much extra pace loss the model expects for each additional lap on this tyre set. This is a lap-time estimate, not measured physical wear.',
    'Next lap · pace loss': 'Estimated time lost next lap versus a fresh tyre of the same compound. The range includes model uncertainty and can cross zero.',
    'Clean laps used': 'Laps accepted by the model after filtering pit laps, cautions, traffic and invalid records. More usable evidence can help constrain the estimate.',
    'Modelled finish': 'The median finish-time change versus the recorded race. Earlier means the changed plan is faster in this simulation; rivals are not simulated.',
    'Probability of gain': 'The share of modelled outcomes that finish sooner than the comparison plan. It is not a chance of winning the race.',
    '80% outcome range': 'The central range from the 10th to the 90th percentile of simulation results. If it crosses zero, both gaining and losing time are plausible.',
    '90% model range': 'The model’s uncertainty interval. A wide band means the exact pace loss is uncertain; it is not a guarantee of real-world coverage.',
    'Modelled gain vs pre-race plan': 'Time saved relative to the remaining frozen pre-race plan. Positive gain is faster. This differs from Ghost finish delta, where negative is faster.',
    'Soft': 'The saved forecast for the soft compound. The curve shows how its tyre pace loss changes with age; actual performance depends on the race conditions.',
    'Medium': 'The saved forecast for the medium compound. Compare both its starting pace and degradation rate before choosing a stint.',
    'Hard': 'The saved forecast for the hard compound. A slower starting tyre can still be useful if its pace degrades more slowly over a long stint.',
}


def tip(label, explanation=None):
    text = explanation or GLOSSARY.get(label)
    if not text:
        return esc(label)
    return (f'<span class="orb-tip" tabindex="0" aria-label="{esc(label)}: {esc(text)}">{esc(label)} '
            f'<span class="orb-info" aria-hidden="true">i</span><span role="tooltip">{esc(text)}</span></span>')
