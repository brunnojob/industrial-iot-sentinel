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

## Implementation update

Sensor specifications require finite calibration endpoints and unique sensor identifiers. Readings reject invalid clocks, timestamps, non-finite values and invalid sequence numbers before advancing sensor state.

Contribution trailer: `Co-authored-by: nyctophile <329826984+ineedfoundmyway@users.noreply.github.com>`.

## Execution proof

[![Executable proof](https://github.com/brunnojob/industrial-iot-sentinel/actions/workflows/proof.yml/badge.svg)](https://github.com/brunnojob/industrial-iot-sentinel/actions/workflows/proof.yml)

![Recorded program execution](docs/proof/execution.svg)

[Verified run](https://github.com/brunnojob/industrial-iot-sentinel/actions/runs/38017501360) · [Execution report](docs/proof/evidence.json)

Run `python .proof/record.py` after installing the prerequisites above. The scenarios execute repository code and verify exit codes and expected output. CI publishes `execution-proof` with the transcript, input fingerprints and source commit. The downloadable report identifies the exact tested version; the workflow badge tracks the latest run.
