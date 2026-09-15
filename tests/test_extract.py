from agent.extract import _fallback_extract

def test_fallback_extracts_watchout_and_deviation():
    turns = [
        {'speaker': 'a', 'text': 'R2 is running hot again.'},
        {'speaker': 'b', 'text': 'When R2 runs hot, first check the valve.'},
    ]
    r = _fallback_extract(turns)
    assert r['entry_count'] == 2
    types = {e['entry_type'] for e in r['entries']}
    assert 'watch_out' in types
    assert 'deviation_observation' in types

def test_fallback_empty():
    r = _fallback_extract([{'speaker': 'a', 'text': 'all fine'}])
    assert r['entry_count'] == 0
