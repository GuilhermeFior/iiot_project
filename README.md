# Arquitetura IIoT para monitoramento de neutralização de pH

Protótipo para geração, transmissão, ingestão e armazenamento de dados de um processo simulado de neutralização de pH. O projeto compara uma coleção documental convencional do MongoDB com uma coleção MongoDB Time Series e avalia a adequação dos dados para consultas temporais e detecção de anomalias.

## Arquitetura inicial

```text
Simulador Python -> publicador MQTT -> broker Mosquitto -> serviço de ingestão -> MongoDB
```

O contrato das mensagens está definido em [docs/data_contract.md](docs/data_contract.md).

## Estrutura do projeto

```text
config/             Configuração dos serviços locais
docs/               Contratos e decisões de arquitetura
src/simulator/      Modelo do processo e controlador Fuzzy-PI
src/publisher/      Publicação de medições no MQTT
src/ingestion/      Validação e persistência das mensagens
src/analysis/       Consultas, benchmarks e detecção de anomalias
tests/              Testes automatizados
```

## Pré-requisitos

- Docker Desktop com Docker Compose.
- Python 3.12 ou versão compatível.

## Inicialização do ambiente local

1. Copie `.env.example` para `.env` e substitua a senha local do MongoDB.
2. Inicie os serviços:

   ```powershell
   docker compose up -d
   ```

3. Confirme o estado dos contêineres:

   ```powershell
   docker compose ps
   ```

O Mosquitto ficará disponível em `localhost:1883` e o MongoDB em `localhost:27017`. A configuração do broker aceita conexões anônimas somente para desenvolvimento local.

## Simulação e publicação de telemetria

Após instalar as dependências Python, envie três mensagens de teste para o broker local:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.publisher.publish_telemetry --count 3 --interval 0.5
```

O publicador utiliza o tópico e os parâmetros definidos em `.env`. Cada mensagem
contém o estado de um tanque de neutralização simplificado e a ação do
controlador Fuzzy-PI sobre a vazão de ácido. O modelo, suas hipóteses e as
equações empregadas estão em [docs/simulation_model.md](docs/simulation_model.md).

Para publicar uma série com uma perturbação controlada na vazão afluente, use:

```powershell
.\.venv\Scripts\python.exe -m src.publisher.publish_telemetry --count 60 --interval 0.1 --disturbance-start 20
```

`--interval` controla o intervalo real de publicação; `--simulation-step`
controla os segundos avançados pela planta a cada mensagem e vale 1 por padrão.

## Geração de dados em lote

Para formar uma base de avaliação, mantenha o serviço de ingestão em execução e
execute, em outro terminal, o gerador em lote:

```powershell
.\.venv\Scripts\python.exe -m src.publisher.generate_dataset --count 1000 --normal-before 300 --disturbance-duration 120
```

O lote contém 300 medições normais, 120 medições de perturbação de processo e
580 medições de recuperação. O envio é rápido por padrão, mas o campo
`timestamp` acompanha o tempo simulado; `received_at` registra o momento real
de persistência. Para reduzir a taxa de envio, informe `--interval`, por
exemplo `--interval 0.01`.

## Análise comparativa das coleções

Com a base já ingerida, execute consultas equivalentes e registre as latências
em um arquivo local:

```powershell
.\.venv\Scripts\python.exe -m src.analysis.benchmark_queries --iterations 20 --warmup 5 --series-limit 250
```

O script mede recuperação de telemetria recente, filtro de perturbações e resumo
agregado para as coleções documental e Time Series. Os resultados ficam em
`artifacts/analysis/benchmark_results.json`; o protocolo está documentado em
[docs/analysis_protocol.md](docs/analysis_protocol.md).

## Detector inicial e artefatos para o relatório

O detector robusto de desvio da vazão afluente usa os rótulos simulados apenas
para avaliação posterior:

```powershell
.\.venv\Scripts\python.exe -m src.analysis.anomaly_detection --collection timeseries
.\.venv\Scripts\python.exe -m src.analysis.report_artifacts
```

Os comandos produzem, em `artifacts/analysis/`, a matriz de confusão e métricas
do detector, uma tabela Markdown com os resultados de benchmark e o gráfico SVG
`telemetry_overview.svg`. Consulte [docs/anomaly_detection.md](docs/anomaly_detection.md)
para as hipóteses e limitações do método.

## Serviço de ingestão

Em outro terminal, inicie o consumidor antes de publicar mensagens:

```powershell
.\.venv\Scripts\python.exe -m src.ingestion.consume_telemetry
```

O serviço valida o contrato e grava cada medição nas coleções `telemetry_documents` e `telemetry_timeseries` quando `MONGO_STORAGE_MODE=dual`. Para um teste que se encerra automaticamente após três mensagens válidas, use:

```powershell
.\.venv\Scripts\python.exe -m src.ingestion.consume_telemetry --max-messages 3
```
