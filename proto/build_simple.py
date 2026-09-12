"""Orb v1 explained simply -> out/Orb_v1_Explained_Simply.pdf"""
import json, numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image, KeepTogether
matplotlib.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False})
# ---------- figures (light theme) ----------
fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=160)
labels = ['Straight line\nthrough Friday laps', 'Friday, after\ncleaning', 'What the race\nactually showed']; vals = [0.285, 0.122, 0.042]; cols = ['#9CA3AF', '#F2C230', '#111827']
b = ax.bar(labels, vals, color=cols, width=0.55)
for r, v in zip(b, vals): ax.text(r.get_x() + r.get_width() / 2, v + 0.006, f'{v:.3f} s per lap', ha='center', fontsize=10)
ax.set_ylabel('How much slower the tyre gets\nevery lap it is used (seconds)'); ax.set_ylim(0, 0.34); ax.set_title('Hungary 2026, medium tyre', loc='left', fontsize=12, weight='bold'); ax.grid(axis='y', alpha=0.3)
fig.tight_layout(); fig.savefig('out/simple_fig1.png'); plt.close(fig)
fig, ax = plt.subplots(figsize=(7.6, 3.2), dpi=160)
parts = [('The tyre\nwearing', 0.045, '#111827'), ('Fuel burning off\n(car gets lighter)', -0.033, '#60A5FA'), ('Track getting\ngrippier', -0.012, '#34D399'), ('Driver pushing\nharder each lap', -0.030, '#F59E0B'), ('Following\nanother car', 0.020, '#F87171')]
x = np.arange(len(parts)); ax.bar(x, [p[1] for p in parts], color=[p[2] for p in parts], width=0.6); ax.axhline(0, color='#374151', lw=0.8)
ax.set_xticks(x); ax.set_xticklabels([p[0] for p in parts], fontsize=8.5); ax.set_ylabel('Change in lap time per lap\n(seconds; + slower, - faster)')
ax.set_title('What a Friday lap time is made of (illustrative sizes)', loc='left', fontsize=12, weight='bold'); ax.grid(axis='y', alpha=0.3); fig.tight_layout(); fig.savefig('out/simple_fig2.png'); plt.close(fig)
fig, ax = plt.subplots(1, 2, figsize=(7.2, 3.0), dpi=160)
ax[0].bar(['Straight line', 'Orb v1'], [0.137, 0.023], color=['#9CA3AF', '#111827'], width=0.55); ax[0].set_title('Average error against the race\n(seconds per lap, lower is better)', fontsize=10, loc='left'); ax[0].set_ylim(0, 0.17); ax[0].grid(axis='y', alpha=0.3)
for i, v in enumerate([0.137, 0.023]): ax[0].text(i, v + 0.004, f'{v:.3f}', ha='center', fontsize=10)
ax[1].bar(['Straight line', 'Orb v1'], [0.20, 0.78], color=['#9CA3AF', '#111827'], width=0.55); ax[1].set_title('How well predictions track the race\n(1.0 is perfect, 0 is no relation)', fontsize=10, loc='left'); ax[1].set_ylim(0, 1); ax[1].grid(axis='y', alpha=0.3)
for i, v in enumerate([0.20, 0.78]): ax[1].text(i, v + 0.02, f'{v:.2f}', ha='center', fontsize=10)
fig.suptitle('11 weekends, 29 tyre-and-weekend cases, each predicted without seeing its own race', fontsize=9.5, x=0.02, ha='left'); fig.tight_layout(); fig.savefig('out/simple_fig3.png'); plt.close(fig)
# ---------- document ----------
ss = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=ss['Heading1'], fontSize=19, leading=23, spaceBefore=6, spaceAfter=10)
H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontSize=13, spaceBefore=10, spaceAfter=5)
B = ParagraphStyle('B', parent=ss['BodyText'], fontSize=11, leading=16, spaceAfter=7)
BIG = ParagraphStyle('BIG', parent=B, fontSize=12.5, leading=18, spaceAfter=9)
SM = ParagraphStyle('SM', parent=B, fontSize=9, leading=12, textColor=colors.HexColor('#4B5563'))
BUL = ParagraphStyle('BUL', parent=B, leftIndent=14, bulletIndent=3, spaceAfter=4)
CELL = ParagraphStyle('CELL', parent=B, fontSize=9.5, leading=12.5, spaceAfter=0); CELLB = ParagraphStyle('CELLB', parent=CELL, fontName='Helvetica-Bold')
def P(t, s=B): return Paragraph(t, s)
def bullets(items, s=BUL): return [Paragraph(t, s, bulletText='•') for t in items]
def table(rows, widths):
    data = [[Paragraph(str(c), CELLB if i == 0 else CELL) for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1); t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#C7CCD4')), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E5E7EB')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)])); return t
def fig_(path, w, cap):
    im = Image(path); r = im.imageHeight / im.imageWidth; im.drawWidth = w * cm; im.drawHeight = w * cm * r; return KeepTogether([im, Spacer(1, 2), P(cap, SM)])
S = []
S += [Spacer(1, 1.5 * cm), P('Orb v1, explained simply', ParagraphStyle('T', parent=ss['Title'], fontSize=28, leading=34, alignment=0)),
      P('What we are trying to do, where the idea and the tools come from, and how we know it works. Written for someone who has never looked at a lap chart.', ParagraphStyle('ST', parent=B, fontSize=13, leading=18, textColor=colors.HexColor('#374151'))),
      Spacer(1, 10), P('Team Orb v1 &middot; TrackShift 2026 &middot; 12 September 2026', SM), Spacer(1, 18),
      P('The whole idea in five sentences', H2)]
S += bullets(['A racing tyre gets a little slower every lap it is used. How much slower per lap is called <b>degradation</b>.',
              'Teams must know it <b>before</b> the race, to decide when to stop for new tyres. The only data before the race comes from Friday practice, and Friday laps are polluted by things that have nothing to do with the tyre.',
              'Orb v1 takes the free public timing data, removes the pollution lap by lap, and produces a clean degradation curve for each tyre type.',
              'Then it learns, from earlier race weekends, how much gentler drivers are with tyres on Sunday than on Friday, and corrects for that too.',
              'Every Sunday night it checks its own prediction against the real race and shows the score. When Friday cannot support an answer, it says so instead of guessing.'], BIG)
S += [PageBreak(), P('1. The problem, with an ice cube', H1),
      P('Imagine you want to know how fast an ice cube melts. You put it on a table and start a stopwatch. But while you are timing it, someone opens a window, someone else turns on a heater, people walk past and cast shadows on it, and your stopwatch runs a bit fast. The number you write down is not the ice cube\'s melting time. It is the story of the room.'),
      P('A Formula 1 lap on a Friday is exactly that. Every lap time mixes five things, and only one of them is the tyre:')]
S += bullets(['<b>The tyre wearing.</b> This is what we want. It makes the car a little slower each lap.',
              '<b>Fuel burning off.</b> The car starts a run heavy and gets lighter every lap, about 1.1 kg a lap, and lighter means faster, roughly 0.03 seconds per lap. This hides the tyre wearing, because one effect makes the car faster while the other makes it slower.',
              '<b>The track getting grippier.</b> As cars lay rubber on the tarmac, everyone goes faster as the session goes on. At Madrid on Friday the track gained about 0.6 seconds per hour on its own.',
              '<b>Following another car.</b> Driving close behind someone costs downforce and time. That lap is slow because of traffic, not the tyre.',
              '<b>The driver.</b> Drivers warm up, learn the track, push harder or ease off. A lap can get faster because the driver is trying harder, and slower because the driver is saving the tyre.'])
S += [fig_('out/simple_fig2.png', 15, 'Figure 1. A Friday lap time is a sum of parts. The sizes are illustrative; the point is that the tyre is one part of five, and the others often pull the opposite way.'),
      P('Now the number that started this project. At the 2026 Hungarian Grand Prix, if you draw a straight line through Friday\'s long-run laps for the medium tyre, it says the tyre gets 0.285 seconds slower every lap. The race showed 0.042. Seven times wrong. A plan built on the Friday line would have lost 74 seconds, more than a pit stop, against the best plan.')]
S += [PageBreak(), P('2. What we wish to solve', H1),
      P('On Saturday night the race strategist asks three questions: how much slower will each tyre be after 20 laps, at what point does the harder tyre become the better one, and should we stop once or twice? A degradation curve is the answer to all three, and if the curve is wrong by a factor of seven, the whole plan is wrong.'),
      P('Formula 1 teams have private sensors and forty engineers, so they get by. But Formula 2, Formula 3, F1 Academy, Indian F4 and the broadcasters who explain strategy on television have only the public timing data and, in the junior series, two engineers. They are our customer. Orb v1 works for any Grand Prix weekend by name, from free data, on a laptop.'),
      P('There is a second problem hiding behind the first. Even a perfectly cleaned Friday curve is not Sunday\'s curve, because on Friday drivers attack the tyres to learn about them and on Sunday they nurse them to make them last. Nobody publishes how big that gap is. We measured it: across this season the medium tyre degrades in the race at only about half of its cleaned Friday rate, while soft and hard transfer roughly one to one. So Friday lies twice: once about what the tyre did, and once about what it will do on Sunday. We correct the lie we can measure and learn the one we cannot.')]
S += [P('3. How we clean a lap, in words', H1),
      P('<b>Step 1. Throw away laps you cannot trust.</b> Laps with a pit stop in them, laps under yellow flags, laps that were deleted by the stewards, laps where the car was stuck behind someone for more than 30% of the distance, cool-down laps, and laps whose telemetry is broken. Every thrown-away lap is listed with its reason, so nobody can accuse us of hiding data.'),
      P('<b>Step 2. Compare each run only to itself.</b> We never compare one driver\'s lap to another driver\'s lap. We compare lap 10 of a run to lap 2 of the same run, same car, same driver, same set of tyres. That removes the driver, the car and the fuel load in one move. Economists have used this trick since the 1970s to compare people to themselves over time instead of to each other; it is called fixed effects.'),
      P('<b>Step 3. Subtract the fuel.</b> We know from the regulations how much fuel burns per lap and roughly what a kilogram is worth, so we subtract it as a known quantity. We do not try to measure it from Friday, because within one run fuel and tyre age change together lap for lap and cannot be told apart.'),
      P('<b>Step 4. Subtract the track getting grippier.</b> We measure this from every driver\'s fastest laps across the session: fresh tyres, different times of day, so the effect of time on the track separates cleanly from the effect of age on the tyre.'),
      P('<b>Step 5. What is left is the tyre.</b> A clean curve: seconds lost per lap of tyre age, for each tyre type, with an honest error bar.'),
      fig_('out/simple_fig1.png', 14, 'Figure 2. Hungary 2026, medium tyre. Cleaning takes the Friday number from 0.285 to 0.122. Learning how Sunday is managed takes it the rest of the way toward the race\'s 0.042.')]
S += [Spacer(1, 6), P('4. How we learn the Sunday lie', H1),
      P('We run the very same cleaning on the race laps too. So for every past weekend we have two clean numbers per tyre: what Friday said and what Sunday did. The ratio between them is how much the drivers managed that tyre. For a new weekend we apply the typical ratio from earlier weekends, in the same way a weather forecaster who knows their model always runs two degrees warm corrects for it before publishing.'),
      P('We only apply a ratio when the earlier weekends agree with each other. For the medium tyre they do, about 0.45. For the hard tyre they do not, so we leave the cleaned Friday curve alone and say so. This is learned from data, and it is re-learned every Sunday night when a new race is added.')]
S += [P('5. How we know it works', H1),
      P('The test is simple to describe. Take one weekend. Pretend we have not seen its race. Predict its Sunday from its Friday plus what the <i>other</i> weekends taught us. Then look at the real race and measure the miss. Do that for every weekend. We never let a weekend see its own answer.'),
      fig_('out/simple_fig3.png', 15, 'Figure 3. The straight line through Friday laps misses the race by 0.137 seconds per lap on average; Orb v1 misses by 0.023. Orb v1 is closer on 28 of the 29 cases.'),
      P('<b>Saying "I do not know" is part of the method.</b> On 13 of the 29 cases Friday did not contain a trustworthy curve: too few laps, or the cleaned line pointed the wrong way. Instead of forcing an answer we mark the tyre <i>withheld</i> and forecast "low degradation, about 0.03 seconds per lap", because that is what every previous withheld case turned out to be. All 13 were low-degradation races. That rule is scored like everything else.')]
S += [P('6. The thing we discovered on the way', H1),
      P('Sometimes Friday appears to show the tyre getting <i>faster</i> with age, which is impossible. Why? Because the driver was ramping up: warming into the run, learning a new track, or nursing a hard tyre early and pushing later. Lap times fall faster than fuel alone explains, and a naive method reads that as negative wear.'),
      P('We can see it happening. From the car\'s public speed and position trace we compute how much energy the driver put through the tyres on each lap, roughly like counting how hard a cyclist is pedalling from their speed and the corners they take. On every impossible Friday, the pedalling got harder lap by lap. On every trustworthy Friday it stayed flat. That is a fifth pollutant, the driver\'s push profile, that nobody else removes, and we found it in the data rather than assuming it. We also found that the "price" of one unit of that energy in lap time is the same on Friday and Sunday at the same circuit, which tells us the measurement is physical, not a statistical accident.')]
S += [PageBreak(), P('7. Where the tech comes from', H1),
      table([['Piece', 'Where it comes from', 'What we did with it'],
             ['The data', 'Formula 1\'s live timing feed, the same one television graphics use. Read with FastF1, an open-source Python library (2020 onward), and OpenF1, a free web service.', 'Downloaded every 2026 weekend and fourteen 2025 weekends: lap times, tyre type and age, flags, weather, and the car\'s speed and position about four times a second.'],
             ['Comparing a run to itself', 'Fixed-effects regression, from econometrics (1970s).', 'One constant per run absorbs the driver, the car and the fuel load, so only the change within a run measures the tyre.'],
             ['Fuel and grip physics', 'The 2026 technical regulations and race engineering practice: about 1.1 kg of fuel per lap, about 0.03 s per kg; rubber laid on the track makes it faster.', 'Fuel is subtracted as a known quantity; track evolution is measured per session from everyone\'s fastest laps.'],
             ['Traffic', 'The feed publishes the gap to the car ahead.', 'Laps spent more than 30% of the distance within 60 m of another car are dropped.'],
             ['The push measurement', 'School mechanics: energy from speed squared times how tightly the car is turning, plus energy from speeding up and slowing down.', 'A per-lap "how hard was the driver pushing" number, which explains every withheld Friday.'],
             ['Learning the Sunday ratio', 'Cross-validation, the standard way statisticians and machine-learning people test a prediction: hide the answer, predict, compare. The bootstrap (1979) for error bars.', 'Every number we show was produced without looking at that weekend\'s race.'],
             ['The liquid neural network', 'MIT (Hasani, Lechner, Rus, 2020 to 2022): a small neural network inspired by a worm\'s nervous system that models things changing continuously in time.', 'We trained it on race laps to see if it beats our simple line. Given the same inputs, it does not. The inputs were the real discovery. We say so.'],
             ['The dashboard', 'Streamlit, an open-source Python tool for data apps.', 'Six screens: live weekend, strategy, the network test, the season score, every dropped lap, the method.'],
             ['What came before', 'One published paper on public F1 data (a Bayesian model of one driver in one race) and two rival hackathon repos we studied.', 'Ours starts from practice, removes five pollutants, and is scored across eleven weekends. The rivals either replay past races or gave up on practice curves.']], [3.2 * cm, 7 * cm, 6.6 * cm])]
S += [Spacer(1, 6), P('8. What the finished thing looks like', H1),
      P('One results file, produced by one command for any Grand Prix, feeds everything: the dashboard, the strategy call and the slides. So the same number appears everywhere.'),
      table([['You see', 'It tells you'],
             ['Weekend screen', 'For each tyre: the predicted Sunday degradation with an error band, or "withheld" with the reason and the low-degradation forecast. For past weekends, the prediction next to what the race did.'],
             ['Strategy screen', 'When the soft and the medium cross, the best one-stop and two-stop plans with stint lengths, and, for past races, how many seconds each Friday view would have cost you.'],
             ['Season score', 'The table in Figure 3, every case, plus the list of withheld cases and what the race did.'],
             ['Dropped laps', 'Every lap we threw away, with its reason.'],
             ['Madrid, live', 'This weekend\'s curves, issued from Friday practice before qualifying, published with a timestamp, scored after Sunday\'s race.']], [3.4 * cm, 13.4 * cm]),
      P('9. What "winning" means for us', H2),
      P('Not that every prediction is right. That the prediction is honest, scored in public, better than the naive method by a wide margin, and that when the data cannot support a curve the tool says so and still gives the strategist something useful. Madrid is the live test: our forecast is on record before the race; on Sunday night we publish the score whatever it says.')]

S += [PageBreak(), P('11. The other teams, and how we compare', H1),
      P('We searched GitHub and the web on the morning of 12 September for every public TrackShift 2026 project on the tyre problem. Whether each team made the final seventy we do not know. Here is what each one does, in plain words, and where we stand against it.'),
      table([['Team (repo)', 'What they do', 'Where we are ahead', 'Where they are ahead'],
             ['PITWALL (OptimistOtaku)', 'The strongest rival. Same cleaning idea as ours, twelve 2026 weekends. They concluded that Friday curves cannot predict Sunday, dropped tyre age from their model, and instead predict how many seconds a fresh tyre is worth at a pit stop.', 'We deliver what the brief asks for: Friday curves plus a Sunday scorecard. We show the curve does transfer once you learn the Sunday ratio (correlation 0.78 versus 0.20). We remove a fifth pollutant, the driver\'s push, that they do not. We forecast a live weekend; they replay old ones.', 'Their statistics are more formal: they estimate the fuel effect from race data instead of assuming it, and they published three checks that falsified their own ideas. Their documents and fallback demo are very polished.'],
             ['GripTrace (RizaShaik)', 'One weekend, 2023 Bahrain, soft tyre only. Careful cleaning with traffic as a covariate, refuses to model fuel at all. Their finding: the Friday trend cannot be trusted as tyre wear.', 'They stopped at "cannot be trusted" on one weekend and one compound. We went to eleven weekends, three compounds, and a validated forecast.', 'Very careful statistical language. A good example of how to describe uncertainty.'],
             ['TyreIQ (suganya1703)', 'A gradient-boosting model that predicts lap time, trained on synthetic 2023 Bahrain data, with a pit-window advisor and a four-tab dashboard. Nine GitHub stars.', 'Their accuracy (R-squared 0.98) is measured on data they generated themselves; ours is measured against eleven real races we did not look at.', 'A clean, friendly dashboard with a pit advisor.'],
             ['Dr.Tyre (Shall We Develop)', 'A cleaning pipeline (fuel, track evolution, traffic) feeding a neon race simulator with an "AI race engineer".', 'No held-out validation numbers are published; no Sunday scorecard; no live weekend.', 'A striking simulator and walkthrough for a demo.'],
             ['TIREX (Tanish9022)', 'A plan for a Kalman state-space model with a physics confounder engine and uncertainty. Only the backend data phases exist so far.', 'We have results; they have architecture.', 'If finished, a principled uncertainty model.'],
             ['TrackShift AI (Icey067)', 'A React dashboard with a Gemini voice race engineer. The cleaning uses fixed constants and simulated toggles; accuracy is quoted in-sample.', 'Every one of our numbers is measured from real laps and tested on races the model never saw.', 'The most visually impressive demo of the group.'],
             ['Empirical substantiation (vib06hav)', 'A 2023 to 2025 practice-only study that concludes public data cannot identify a stable degradation estimate.', 'Twenty-nine held-out cases say it can, once Sunday management is learned and the untrustworthy Fridays are withheld.', 'A useful warning, honestly stated.'],
             ['Others', 'Simulation-only engines, an unfinished decision engine, empty repositories.', 'Real data, real races, real scores.', 'Nothing we could verify.']], [3 * cm, 5.2 * cm, 4.6 * cm, 3.8 * cm]),
      P('In one line: nobody else delivers a Friday curve that is scored against Sunday across a season, says "withheld" when it should, removes the driver\'s push, and forecasts a live weekend. The one team with comparable rigour, PITWALL, chose not to deliver the curve at all.', BIG)]
S += [P('12. Ten questions a mentor might ask you, and the short answers', H1)]
for q, a in [
 ('Why not just use last year\'s race to predict this one?', 'Cars, tyres and tracks change, and this year\'s Friday is the freshest evidence. We do use past races, but for one thing only: to learn how much gentler Sunday is than Friday for each tyre.'),
 ('How is this different from drawing a line through Friday\'s laps?', 'The line mixes five things; we remove four of them lap by lap and measure the fifth. At Hungary the line was seven times wrong; ours was close.'),
 ('What if it rains on Friday?', 'Wet laps are thrown out. If the whole day is wet, every tyre is withheld and the tool says so instead of guessing.'),
 ('Why should I believe 0.023 seconds?', 'Because every weekend was predicted without looking at its own race, across eleven weekends, and the naive method scored 0.137 on the same test. We also tried different fuel and traffic settings; the answer barely moves.'),
 ('Is "withheld" just a way of not answering?', 'No. Withheld still gives a forecast, low degradation, and that forecast has been right thirteen times out of thirteen.'),
 ('Where is the AI?', 'The Sunday ratio is learned from data and tested on unseen weekends. We also trained a neural network and reported that it did not beat the simple line; the inputs it used were the real discovery.'),
 ('How are you different from PITWALL?', 'They concluded Friday cannot predict Sunday and stopped delivering a curve. We showed it can once you learn the Sunday ratio, we remove the driver\'s push which they do not, and we are forecasting Madrid live rather than replaying old races.'),
 ('Who would actually use this?', 'Junior series such as F2, F3, F1 Academy and Indian F4, and broadcasters. They have the public timing data and two engineers, not forty.'),
 ('What did you build today and what before?', 'The cleaning method and the first six weekends were disclosed pre-work from the idea round. Seven more weekends, the withheld rule, the push measurement, the strategy layer, the network test, the dashboard and Madrid live were built here.'),
 ('What happens on Sunday night?', 'The race laps go through the same cleaning, the prediction is compared with the race, and the score is published whatever it says. The Madrid forecast is on record before the race.')]:
    S += [KeepTogether([P(f'<b>{q}</b>', B), P(a)])]

S += [      P('10. Words you will hear, in one line each', H2),
      table([['Word', 'Meaning'], ['Compound', 'The tyre type: soft (fast, wears quickly), medium, hard (slow, lasts).'], ['Stint or run', 'The laps driven on one set of tyres between pit stops.'], ['Tyre age', 'How many laps a set of tyres has done.'],
             ['Degradation', 'How much slower the tyre gets per lap of age, in seconds per lap.'], ['Long run', 'A practice run of many laps in a row, meant to imitate the race.'], ['Fuel prior', 'The fuel effect we subtract as a known number instead of measuring it.'],
             ['Track evolution', 'The track getting faster as rubber goes down.'], ['Traffic', 'Laps spent close behind another car.'], ['Fixed effect', 'The "compare each run to itself" trick.'], ['Gate', 'The rule that decides whether Friday supports a curve at all.'],
             ['Withheld', 'No trustworthy curve; forecast low degradation instead.'], ['Transfer factor', 'How much Sunday shrinks the Friday number for a given compound.'], ['Leave-one-weekend-out', 'Testing by hiding each weekend\'s race in turn.'],
             ['Band', 'The error bar: where the true number probably lies.'], ['Crossover lap', 'The tyre age at which the harder tyre becomes the faster one.'], ['Push profile', 'How hard the driver was pushing, lap by lap, measured from energy.'],
             ['Lock file', 'The single results file everything reads from.'], ['Naive line', 'A straight line through Friday laps with no cleaning: the thing we beat.']], [3.6 * cm, 13.2 * cm])]
doc = SimpleDocTemplate('out/Orb_v1_Explained_Simply.pdf', pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm, bottomMargin=1.8 * cm, title='Orb v1 explained simply', author='Team Orb v1')
def footer(c, d): c.saveState(); c.setFont('Helvetica', 8); c.setFillColor(colors.HexColor('#6B7280')); c.drawString(2 * cm, 1.1 * cm, 'Orb v1 explained simply'); c.drawRightString(A4[0] - 2 * cm, 1.1 * cm, str(d.page)); c.restoreState()
doc.build(S, onFirstPage=footer, onLaterPages=footer); print('built')
