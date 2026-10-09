# Industrial IoT Sentinel

An operational vessel occupancy twin with zone capacity, personnel roles, and idempotent movements recovered from a SQLite journal.

## Run

Requirements: Python 3.11+.

```sh
python -m unittest discover
python events.py configuracao.json --database .local/twin.db < movimentos.jsonl > result.json
```

## Behavior

`DurableTwin` validates a copy of the state before committing a transaction. Capacity failures preserve the previous occupancy. A configuration fingerprint prevents silent configuration changes in an existing database.

## Result synchronization

The [operations archive](https://vercel-home-telemetry-api.vercel.app/laboratory.html?project=industrial-iot-sentinel) stores execution results. Supabase migrations are in the [API repository](https://github.com/brunnojob/vercel-home-telemetry-api/tree/main/supabase/migrations).

```sh
python cloud/sync.py enqueue result.json --project industrial-iot-sentinel
python cloud/sync.py sync
```

Set `BRUNNODEV_ACCESS_TOKEN` to your session token. The SQLite outbox retains reports until the server confirms persistence; identical content does not create duplicate records. Tokens are not stored in source code. To run the synchronization tests:

```sh
python -m unittest discover -s cloud
```
