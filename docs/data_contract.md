# Contrato de dados MQTT

## Objetivo

Este documento define a primeira versão do contrato de mensagens entre o simulador, o broker MQTT e o serviço de ingestão. O contrato é independente da coleção de destino para garantir que os dois modelos do MongoDB recebam a mesma representação lógica da medição.

## Convenções de tópicos

| Finalidade | Tópico | Publicador | Consumidor principal |
|---|---|---|---|
| Telemetria do processo | `tcc/v1/{plant_id}/tanks/{tank_id}/telemetry` | Simulador | Serviço de ingestão |
| Eventos operacionais | `tcc/v1/{plant_id}/tanks/{tank_id}/events` | Simulador | Serviço de ingestão e análise |
| Estado do simulador | `tcc/v1/{plant_id}/tanks/{tank_id}/status` | Simulador | Monitoramento |

Na implementação inicial, o tópico de telemetria será `tcc/v1/simulated-plant-01/tanks/t-01/telemetry`. Os identificadores são escritos em minúsculas, usam hífens quando necessário e não contêm dados pessoais.

## Mensagem de telemetria

Cada publicação deve ser um objeto JSON UTF-8 com a estrutura abaixo.

```json
{
  "schema_version": "1.0",
  "message_id": "b0fd1d11-5d5d-4e96-89d3-2ea4c9bf5772",
  "sequence": 1042,
  "timestamp": "2026-09-07T15:30:00.000Z",
  "source": {
    "plant_id": "simulated-plant-01",
    "tank_id": "t-01",
    "sensor_group": "process"
  },
  "measurements": {
    "ph": 7.02,
    "effluent_flow_l_s": 10.0,
    "acid_flow_l_s": 2.15,
    "temperature_c": 25.0,
    "level_m": 1.2,
    "valve_position_pct": 42.0
  },
  "controller": {
    "setpoint_ph": 7.0,
    "error_ph": -0.02,
    "delta_error_ph": 0.01
  },
  "anomaly": {
    "label": false,
    "type": null
  }
}
```

## Regras de validação

- `schema_version`, `message_id`, `sequence`, `timestamp`, `source` e `measurements` são obrigatórios.
- `message_id` deve ser um UUID v4 e identifica uma publicação individual.
- `sequence` é um inteiro crescente por execução do simulador e permite identificar perdas ou reordenação de mensagens.
- `timestamp` representa o instante de geração da medição em UTC, no formato RFC 3339 com o sufixo `Z`.
- O serviço de ingestão acrescentará um `received_at` em UTC para registrar o instante de recebimento, sem substituir o `timestamp` original.
- O campo `source` será usado como base do `metaField` da coleção MongoDB Time Series; por isso, seus valores devem mudar raramente.
- Os campos de `measurements` são métricas variáveis e devem ser numéricos, exceto o estado lógico do atuador, quando incluído em versões futuras.
- `anomaly.label` indica se a observação faz parte de uma anomalia simulada. Quando for `true`, `anomaly.type` deve conter um dos valores definidos a seguir.

## Tipos iniciais de anomalia

| Tipo | Descrição |
|---|---|
| `process_disturbance` | Alteração anormal em uma condição de processo, como vazão ou concentração de entrada. |
| `sensor_noise` | Ruído de medição acima do comportamento esperado. |
| `sensor_stuck` | Leitura congelada apesar da variação do processo. |
| `sensor_out_of_range` | Valor fisicamente implausível ou fora da faixa operacional definida. |
| `communication_delay` | Mensagem recebida após atraso artificial. |

## Qualidade de serviço e duplicidade

O MVP utilizará MQTT com QoS 0 para validar o fluxo completo com a menor sobrecarga possível. `message_id` e `sequence` permanecem obrigatórios para que perdas possam ser identificadas. Em um cenário posterior com QoS 1, a camada de ingestão deverá detectar duplicidades antes da escrita nas coleções de avaliação, já que coleções MongoDB Time Series possuem restrições para índices únicos.

## Mapeamento para o MongoDB

Na coleção MongoDB Time Series, `timestamp` será configurado como `timeField` e `source` como `metaField`. Os campos `measurements`, `controller` e `anomaly` serão armazenados como métricas ou informações associadas à medição. A coleção documental convencional receberá a mesma estrutura lógica, permitindo comparações justas entre os modelos.
