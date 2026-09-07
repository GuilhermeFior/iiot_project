# Perfis de anomalia simulada

O gerador de lote possui dois perfis. O padrão `process_only` preserva a série
anterior: uma perturbação física aumenta a vazão afluente e mobiliza o
controlador Fuzzy-PI. O perfil `all_types` gera, além desse evento, janelas não
sobrepostas para todos os tipos definidos no contrato.

| Tipo | Camada afetada | Comportamento simulado |
|---|---|---|
| `process_disturbance` | Processo | Acréscimo de 1,5 L/s à vazão afluente por período definido. |
| `sensor_noise` | Observação | Perturbação determinística de até 0,35 unidade na leitura de pH. |
| `sensor_stuck` | Observação | Leitura de pH congelada no primeiro valor da janela. |
| `sensor_out_of_range` | Observação | pH registrado como 13,5: extremo operacional, porém válido no contrato físico de 0 a 14. |
| `communication_delay` | Comunicação | `timestamp` reduzido em 30 segundos; `received_at` preserva o horário real de recebimento. |

As falhas de sensor e de comunicação não alteram o estado interno do tanque ou
a ação do controlador; elas representam exclusivamente o que chega à camada de
ingestão. Isso permite diferenciar anomalia de processo de anomalia de medição.

## Execução

O comando abaixo gera 1.000 mensagens com 300 medições normais iniciais, 120 de
perturbação de processo, quatro janelas de 60 mensagens para os demais tipos,
40 medições normais entre janelas e recuperação ao final:

```powershell
.\.venv\Scripts\python.exe -m src.publisher.generate_dataset --count 1000 --normal-before 300 --disturbance-duration 120 --anomaly-profile all_types
```

O consumidor MQTT deve estar em execução antes da publicação. Nesse exemplo, o
perfil insere 360 mensagens rotuladas: 120 de perturbação de processo e 60 de
cada um dos quatro tipos restantes.
