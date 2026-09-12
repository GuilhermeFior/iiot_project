# Conclusão da análise técnica

## Escopo e evidências

O protótipo validou o caminho completo: simulador de neutralização de pH com controlador Fuzzy-PI, publicação MQTT, broker Mosquitto, validação e ingestão, e persistência dual em MongoDB documental e MongoDB Time Series. Ao final dos ensaios, cada coleção possuía 110.050 mensagens.

O benchmark funcional foi limitado às 100.000 mensagens sem o campo `experiment`, para não misturar a base principal aos lotes de validação. A série cobre aproximadamente 27,8 horas de tempo simulado e contém 12.000 perturbações de processo. O ensaio final utilizou 10 repetições medidas, 2 aquecimentos, limite de 250 documentos para telemetria recente e janelas de 1 h, 6 h e 24 h. As consultas materializam os resultados no cliente; as latências representam este ambiente local, não uma projeção universal de produção.

## Comparação Documental × Time Series

| Consulta | Documental — média (ms) | Time Series — média (ms) | Resultado |
|---|---:|---:|---|
| Telemetria recente (250) | 48,6330 | 62,5594 | Documental mais rápida. |
| Perturbações de processo (12.000) | 486,9853 | 336,5684 | Time Series mais rápida na média. |
| Resumo agregado | 360,3218 | 308,8432 | Time Series mais rápida na média. |
| Janela de 1 h | 49,3538 | 62,8208 | Documental mais rápida. |
| Janela de 6 h | 330,3952 | 347,1428 | Documental ligeiramente mais rápida. |
| Janela de 24 h | 1.186,5123 | 1.893,7735 | Documental mais rápida. |

Na consulta de telemetria recente, a coleção documental utilizou `IXSCAN`, enquanto a visão resumida da Time Series mostrou `COLLSCAN`. Portanto, nesta carga, a Time Series não é automaticamente mais rápida em qualquer consulta temporal: o resultado depende do padrão de acesso, do `metaField`, dos índices, da cardinalidade e do volume.

`collStats` é uma estatística global da coleção. Na medição, ambas continham 110.050 mensagens, embora a comparação funcional estivesse filtrada para a base limpa de 100.000 observações.

| Indicador de armazenamento | Documental | Time Series | Redução da Time Series |
|---|---:|---:|---:|
| Tamanho lógico | 56.867.840 B | 5.151.623 B | 90,94% |
| Tamanho físico | 11.321.344 B | 5.206.016 B | 54,02% |
| Índices | 13.541.376 B | 61.440 B | 99,55% |

Os dados sustentam o uso da coleção Time Series como histórico de telemetria pelo ganho de espaço, mantendo a coleção documental para consultas operacionais especificamente indexadas. A escrita dual permite essa escolha sem alterar o contrato MQTT.

## Detecção de anomalias

O experimento isolado `74860e3e-04fa-4d54-978e-8ecda24bfeb2` contém 10.000 observações: 1.500 perturbações de processo, 750 ocorrências de cada uma das quatro falhas adicionais e 5.500 observações normais. Durante a falha de sensor travado, uma excitação física é aplicada ao processo; assim, a anomalia é observável e não consiste apenas em um rótulo artificial.

| Detector | Precisão | Revocação | F1-score |
|---|---:|---:|---:|
| Perturbação de processo | 1,0000 | 1,0000 | 1,0000 |
| Ruído de sensor | 1,0000 | 0,8427 | 0,9146 |
| Sensor travado | 0,9982 | 0,7600 | 0,8630 |
| Leitura fora da faixa | 1,0000 | 1,0000 | 1,0000 |
| Atraso de comunicação | 1,0000 | 1,0000 | 1,0000 |

Os rótulos simulados foram usados somente para calcular as métricas. Ruído e sensor travado apresentam detectores conservadores: quase não geram falsos alarmes, mas deixam de identificar parte dos casos limítrofes. As métricas são evidência controlada do protótipo sobre anomalias simuladas determinísticas, e não uma calibração industrial com dados reais.

## Reprodutibilidade e encerramento

Os resultados locais foram gravados em `artifacts/analysis/benchmark_final_clean_100k.json` e `artifacts/analysis/stuck_observable_10k_validation.json`; o painel correspondente está em `artifacts/dashboard/stuck_observable_10k_dashboard.html`. Esses artefatos são ignorados pelo Git porque dependem da máquina e da base presente. Os comandos para refazê-los estão em `README.md`, `docs/analysis_protocol.md` e `docs/multi_anomaly_detection.md`.

Não há pendência técnica que impeça a redação de metodologia, implementação, resultados e discussão. Uma evolução para produção exigiria ensaios de carga concorrente, política de retenção, autenticação MQTT, criptografia em trânsito, gestão segura de segredos, monitoramento da ingestão e calibração com dados reais. Essas extensões não invalidam os resultados do protótipo acadêmico.
