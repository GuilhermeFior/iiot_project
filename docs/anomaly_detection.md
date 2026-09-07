# Detector inicial de anomalias

## Método

O primeiro detector identifica perturbações de processo pela vazão afluente. A
referência é a mediana da série e a dispersão é estimada pelo desvio absoluto
mediano (MAD), que é robusto à presença de uma minoria de observações anômalas.
Uma leitura é classificada como perturbação quando:

```text
|vazão - mediana| > max(desvio_mínimo, z · 1,4826 · MAD)
```

Os rótulos `process_disturbance` não são usados para calcular a referência ou o
limiar: eles são utilizados somente após a detecção para calcular precisão,
revocação, F1-score e acurácia.

## Escopo

O simulador atual produz uma perturbação que incrementa diretamente a vazão de
entrada. Por isso, este detector é uma linha de base interpretável e não uma
solução geral de detecção de anomalias. A avaliação deve ser ampliada quando a
base incluir os demais tipos definidos no contrato, como ruído, sensor travado e
valor fora de faixa.

## Execução

```powershell
.\.venv\Scripts\python.exe -m src.analysis.anomaly_detection --collection timeseries
```

O resultado é salvo em `artifacts/analysis/anomaly_detection_results.json`.
