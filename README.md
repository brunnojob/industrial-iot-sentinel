# Industrial IoT Sentinel

Gêmeo operacional de ocupação de embarcação, capacidade por zona, função de pessoas e movimentos idempotentes, recuperados de um diário SQLite.

## Executar

Requisitos: Python 3.11+.

```sh
python -m unittest discover
python events.py configuracao.json --database .local/twin.db < movimentos.jsonl > resultado.json
```

## Funcionamento

`DurableTwin` valida em uma cópia antes de confirmar a transação. Falhas de capacidade conservam a ocupação anterior. A configuração é identificada por fingerprint e não pode mudar silenciosamente numa base existente.

## Persistência de resultados

O arquivo de operações está em [vercel-home-telemetry-api.vercel.app](https://vercel-home-telemetry-api.vercel.app/laboratory.html?project=industrial-iot-sentinel). As migrações Supabase estão no [repositório da API](https://github.com/brunnojob/vercel-home-telemetry-api/tree/main/supabase/migrations).

```sh
python cloud/sync.py enqueue resultado.json --project industrial-iot-sentinel
python cloud/sync.py sync
```

Defina `BRUNNODEV_ACCESS_TOKEN` com sua sessão. A fila SQLite conserva os relatórios até confirmação do servidor; o mesmo conteúdo não gera registros duplicados. Tokens não são gravados no código.
