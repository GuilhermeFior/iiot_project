# Modelo de simulação de neutralização de pH

## Escopo e hipóteses

O simulador representa um tanque perfeitamente misturado que recebe um afluente
básico e uma corrente de ácido. Ele é um modelo didático para produzir séries
temporais consistentes e exercitar a arquitetura IIoT; não é uma representação
química completa. A calibração dos parâmetros deve ser feita posteriormente com
dados experimentais ou com o modelo de referência do controlador estudado.

O estado interno é o excesso de equivalentes ácido-base, em mol. Em cada passo,
o balanço de massa considera as correntes de entrada e a descarga homogênea do
tanque:

```text
dE/dt = Qe · Ce - Qa · Ca - (Qe + Qa) · E/V
```

onde `E` é o excesso de base, `Qe` e `Qa` são as vazões de afluente e ácido,
`Ce` e `Ca` são suas concentrações equivalentes e `V` é o volume do tanque.
O pH é calculado a partir de uma aproximação com efeito tampão:

```text
pH = 7 + 2 · asinh((E/V) / beta)
```

O resultado é limitado ao intervalo físico de 0 a 14. O parâmetro `beta`
representa a capacidade tampão aproximada do meio.

## Controlador Fuzzy-PI

O erro é definido como `pH - setpoint`. Portanto, erro positivo indica excesso
de basicidade e deve aumentar a corrente de ácido. O controlador recebe o erro
e sua variação temporal, normaliza ambos em sete conjuntos linguísticos de
`-3` a `+3` e avalia as 49 combinações possíveis. As regras são agregadas por
Mamdani (operadores mínimo e máximo), e a correção incremental da vazão é
obtida pela defuzzificação pelo centroide.

A saída ajusta a vazão de ácido limitada a 0--4 L/s. No ponto nominal, 10 L/s
de afluente com 0,02 mol/L de equivalentes básicos são compensados por 2 L/s
de ácido a 0,10 mol/L.

## Perturbação controlada

O publicador aceita `--disturbance-start`. Quando informada, acrescenta 1,5 L/s
à vazão afluente por 20 segundos simulados. As mensagens desse período recebem
o rótulo de contrato `process_disturbance`, que pode ser usado como verdade de
campo nas etapas futuras de avaliação de detecção de anomalias.
