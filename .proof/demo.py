import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def run(argv, expected=0):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode != expected:
        raise RuntimeError(result.stderr + result.stdout)
    return result.stdout

from events import DurableTwin

config = {'vesselId': 'demo-vessel', 'capacity': 2, 'zones': [{'id': 'deck', 'capacity': 1, 'roles': ['crew']}, {'id': 'bridge', 'capacity': 1, 'roles': ['crew']}], 'people': [{'id': 'one', 'role': 'crew'}, {'id': 'two', 'role': 'crew'}]}
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'twin.db'
    twin = DurableTwin(path, config)
    event = {'eventId': 'first', 'personId': 'one', 'direction': 'embark', 'zoneId': 'deck', 'timestamp': 1000}
    twin.submit(event)
    twin.submit({**event, 'eventId': 'second', 'personId': 'two', 'zoneId': 'bridge'})
    rejected = False
    try:
        twin.submit({**event, 'eventId': 'overflow', 'zoneId': 'bridge'})
    except OverflowError:
        rejected = True
    assert rejected and twin.snapshot()['events'] == 2
    twin.db.close()
    recovered = DurableTwin(path, config)
    replay = recovered.submit(event)
    assert replay['duplicate'] and replay['peopleOnBoard'] == 2
    print(json.dumps({'recovered': recovered.snapshot(), 'capacity_rejection_atomic': rejected, 'replay_idempotent': replay['duplicate']}, sort_keys=True))
    recovered.db.close()
