# Detecção por tipo de anomalia

O script `src.analysis.multi_anomaly_detection` implementa linhas de base
interpretáveis e avalia cada tipo de anomalia separadamente, em esquema
um-contra-todos. Os rótulos são usados somente para calcular as métricas após a
detecção.

| Tipo | Sinal usado | Critério inicial |
|---|---|---|
| `process_disturbance` | Vazão afluente | Desvio robusto em relação à mediana, com MAD. |
| `sensor_noise` | Resíduo entre pH observado e pH estimado pelo controlador | Resíduo maior que 0,05 pH com mudança de leitura. |
| `sensor_stuck` | Repetição de pH com mudança na estimativa do processo | Mesmo pH consecutivo e resíduo entre 0,005 e 0,2 pH. |
| `sensor_out_of_range` | pH observado | Fora da faixa operacional de 5,5 a 8,5. |
| `communication_delay` | Sequência de timestamps por lote | Timestamp mais de 2 s atrás do relógio nominal inferido da sequência. |

O método para atraso avalia o desvio do timestamp em relação ao intervalo
nominal inferido no início de cada lote, e não a subtração direta entre
`received_at` e `timestamp`. Em uma publicação acelerada, o tempo simulado e o
relógio real de ingestão não são comparáveis.

## Execução

```powershell
.\.venv\Scripts\python.exe -m src.analysis.multi_anomaly_detection --collection timeseries
```

Os resultados são gravados em
`artifacts/analysis/multi_anomaly_detection_results.json`.

Para analisar somente uma execução, informe o `run_id` exibido pelo gerador:

```powershell
.\.venv\Scripts\python.exe -m src.analysis.multi_anomaly_detection --collection timeseries --run-id SEU-UUID
```

## Artefatos para o relatório

Após a detecção, o script abaixo gera uma tabela Markdown com todas as métricas
e um gráfico SVG da mesma execução. O gráfico compara o pH transmitido pelo
sensor com o pH reconstruído pelo estado do controlador; assim, o intervalo de
sensor travado pode ser inspecionado visualmente sem misturar lotes distintos.

```powershell
.\.venv\Scripts\python.exe -m src.analysis.report_artifacts `
  --multi-detection-input artifacts/analysis/multi_anomaly_detection_results.json `
  --experiment-markdown-output artifacts/analysis/experiment_detection_summary.md `
  --svg-output artifacts/analysis/experiment_overview.svg
```

Quando o JSON de detecção contém `run_id`, ele é aplicado automaticamente à
consulta da telemetria. Caso seja necessário, o valor pode ser informado de
forma explícita com `--run-id SEU-UUID`.
