# Industrial IoT Sentinel

A telemetry pipeline for validating sensor events, detecting threshold breaches, suppressing duplicate alerts and tracking recovery.

## Run

```bash
python sentinel.py
python -m unittest
```

The core accepts normalized JSON-like readings and has no connection to live industrial equipment.
