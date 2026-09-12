from pathlib import Path
import hashlib,json,zipfile,xml.etree.ElementTree as ET,subprocess,re
root=Path.cwd()
baseline=json.loads((Path(__file__).resolve().parents[1]/'protected_fingerprints.json').read_text())
for name,expected in baseline.items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
forecast=json.loads((root/'out/forecast_Madrid_2026.json').read_text())
lock2=json.loads((root/'out/lock_v2.json').read_text())
assert forecast['lock_v2_forecast_hash']==lock2['shared']['forecast_hash']
assert forecast['lock_v2_sha256']==baseline['out/lock_v2.json']
assert forecast['lock_sha256']==baseline['out/lock.json']
assert (root/'feat/Madrid_Q.csv').exists()
log=(root/'refresh_q.log').read_text()
assert 'second attempt, data window open after 21:30) start Sat Sep 12 21:32:31 IST 2026' in log
assert 'Madrid Q: 219 laps' in log
assert '== Q refresh done Sat Sep 12 21:33:14 IST 2026' in log
assert forecast['sessions_used']==['FP1','FP2','FP3','Q']
assert forecast['issued_at']=='2026-09-12T21:33:14+05:30'
with zipfile.ZipFile(root/'out/Orb_v1_Mentor_Briefing.pptx') as archive:
    mentor=' '.join(ET.fromstring(archive.read('ppt/slides/slide10.xml')).itertext())
    proof=' '.join(ET.fromstring(archive.read('ppt/slides/slide7.xml')).itertext())
    v=lock2['validation']; ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
    table=ET.fromstring(archive.read('ppt/slides/slide7.xml')).find('.//a:tbl',ns)
    actual=[[''.join(tc.itertext()).strip() for tc in row.findall('a:tc',ns)] for row in table.findall('a:tr',ns)]
    expected=[['Predictor','Cases','MAE','Calibration slope','r']]
    for label,n,mae,cal in [('Naive straight line',v['n_compound_weekends'],v['mae_all_with_fallback']['naive'],v['calibration']['naive']),('Cleaned Friday curve, issued',v['n_issued'],v['mae_issued']['clean'],v['calibration']['clean']),('Orb v1, issued',v['n_issued'],v['mae_issued']['clearstint'],v['calibration']['clearstint']),('Orb v1, all cases with fallback',v['n_compound_weekends'],v['mae_all_with_fallback']['clearstint'],v['calibration']['all_with_fallback'])]:
        expected.append([label,str(n),f'{mae:.3f}',f"{cal['slope']:+.2f}",f"{cal['r']:.2f}"])
    assert actual==expected,('mentor proof table does not equal lock v2',actual,expected)
exe='pdftotext'
challenge=subprocess.check_output([exe,'-f','6','-l','6',str(root/'out/Orb_v1_ChallengeDay.pdf'),'-'],text=True)
for slide in (mentor,challenge):
    for name in ('out/forecast_Madrid_2026.json','out/forecast_Madrid_2026.pdf','out/forecast_Madrid_2026.sha256'):
        assert baseline[name] in slide,name
    assert forecast['lock_v2_forecast_hash'].removeprefix('sha256:') in slide
    for compound in forecast['compounds']:
        assert f"{compound['prediction_s_per_lap']:+.3f}" in slide
        assert str(compound['clean_practice_laps']) in slide
    assert '22/34' in slide and 'S-M-M' in slide and '21 s' in slide
    assert 'withheld' in slide and 'no positive degradation signal in cleaned practice' in slide
for compound in forecast['compounds']:
    lo,hi=compound['band90']
    assert f'{lo:+.3f} to {hi:+.3f}' in challenge
    assert f'{lo:+.2f} to {hi:+.2f}'.replace('-', '−') in mentor
text=subprocess.check_output([exe,str(root/'out/Orb_v1_ChallengeDay.pdf'),'-'],text=True)
for stale in ('+0.098', '10 of 31', 'All 13 withheld'):
    assert stale not in text,stale
assert '9 of 31' in text and 'post-race reference model' in text and 'not claim observed race time saved' in text
print('PASS: 9 protected fingerprints; post-21:30 qualifying evidence; frozen source consistency; all 4 full digests on both Madrid slides; exact source-rounded predictions/bands/counts/gates/strategy; all 20 proof-table cells equal lock v2; retired textual claims absent.')
