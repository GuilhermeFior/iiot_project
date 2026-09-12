# Protocolo de análise comparativa

## Objetivo

Comparar a coleção documental convencional e a coleção MongoDB Time Series
usando a mesma telemetria, as mesmas consultas lógicas e o mesmo ambiente local.
O benchmark mede latência de cliente a cliente, portanto serve como evidência
exploratória de desempenho e não como resultado generalizável para produção.

## Consultas avaliadas

| Consulta | Finalidade | Operação MongoDB |
|---|---|---|
| Telemetria recente | Exibir pH, vazões e rótulo das últimas medições do tanque monitorado | `find` por fonte, ordenação por `timestamp` e `limit` |
| Janelas temporais de 1 h, 6 h e 24 h | Recuperar séries completas de períodos operacionais relevantes | `find` por fonte e intervalo de `timestamp` |
| Perturbações de processo | Recuperar observações rotuladas do tanque para avaliação posterior | `find` por fonte e `anomaly.type` |
| Resumo agregado | Calcular contagem, período, estatísticas de pH e vazão de ácido por tanque | `$match` por fonte e `aggregate` com `$group` |

Para cada consulta, o script executa aquecimentos não medidos, repete a operação
um número configurável de vezes, materializa o cursor e registra mínimo, média,
mediana, percentil 95 e máximo. O script também solicita um `explain` de nível
`queryPlanner` para a consulta temporal, registrando uma visão compacta dos
estágios do plano. A filtragem por `plant_id` e `tank_id` mantém a comparação
alinhada ao acesso por fonte previsto pelo `metaField` da coleção Time Series e
ao índice composto da coleção documental.

As janelas são encerradas no maior `timestamp` da base, em vez de no relógio da
máquina. Isso torna o método compatível com telemetria de tempo simulado e
reprodutível após cada lote de dados.

## Execução

Com MongoDB em execução e os dados já ingeridos:

```powershell
.\.venv\Scripts\python.exe -m src.analysis.benchmark_queries --iterations 10 --warmup 2 --series-limit 250 --window-hours 1,6,24
```

O resultado é salvo localmente em `artifacts/analysis/benchmark_results.json`.
Esse caminho é ignorado pelo Git, pois cada execução depende da máquina, da base
presente e do momento da medição. Para o relatório, registre a configuração do
ambiente, o tamanho da base e os valores resumidos desse arquivo.

Para manter a comparação de armazenamento independente dos lotes de validação
mais recentes, use `--without-experiment`. Para analisar somente uma execução
identificada, use `--run-id SEU-UUID`. As estatísticas físicas de armazenamento
continuam sendo da coleção inteira, pois o MongoDB não as calcula por filtro.
