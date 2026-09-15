from agent.rules import analyze_transcript

def test_capture_flow():
    turns = [
        {'speaker': 'shift_lead', 'text': 'Reactor R2 is running hot again this morning.'},
        {'speaker': 'operator', 'text': 'Temperature is at 62 degrees, we pulled the feed back.'},
        {'speaker': 'shift_lead', 'text': 'When R2 runs hot, first check the cooling water valve.'},
    ]
    r = analyze_transcript(turns)
    assert r['urgent'] is True
    assert len(r['issues']) == 1
    assert len(r['watchouts']) == 1

def test_quiet_when_fine():
    turns = [{'speaker': 'a', 'text': 'Good shift, no issues today.'},
             {'speaker': 'b', 'text': 'Everything nominal.'}]
    r = analyze_transcript(turns)
    assert r['urgent'] is False
    assert len(r['issues']) == 0
    assert len(r['watchouts']) == 0
