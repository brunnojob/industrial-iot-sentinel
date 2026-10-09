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

## Optional report archive

Export a JSON report from the command above, then run `python cloud/sync.py enqueue result.json --project industrial-iot-sentinel` and `python cloud/sync.py sync`. Synchronization requires `BRUNNODEV_ACCESS_TOKEN` and the external operations API; the local outbox retains unacknowledged reports.

## License

Original source and documentation are MIT licensed; see [LICENSE](LICENSE). Third-party dependencies and media retain their respective terms. Maintained by [Brunno Dev](https://brunnodev.store).
