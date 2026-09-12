# Entrega de software — protótipo IIoT

## Escopo entregue

O repositório entrega um protótipo executável de monitoramento de neutralização
de pH, composto por:

- simulador físico simplificado e controlador Fuzzy-PI;
- publicadores de telemetria unitária e em lote;
- broker MQTT Mosquitto em Docker;
- serviço Python de validação, ingestão e persistência dual no MongoDB;
- coleções documental e Time Series com o mesmo contrato de telemetria;
- geradores de anomalias, detectores interpretáveis, benchmark e painel HTML;
- documentação de contrato, modelo de simulação, protocolo de análise e
  conclusão técnica.

## Como executar

1. Crie `.env` a partir de `.env.example` e defina uma senha local para o
   MongoDB.
2. Suba os serviços:

   ```powershell
   docker compose up -d
   docker compose ps
   ```

3. Instale as dependências Python:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Em um terminal, inicie a ingestão:

   ```powershell
   .\.venv\Scripts\python.exe -m src.ingestion.consume_telemetry
   ```

5. Em outro terminal, publique uma série de validação:

   ```powershell
   .\.venv\Scripts\python.exe -m src.publisher.generate_dataset `
     --count 1000 --normal-before 300 --disturbance-duration 120 `
     --anomaly-profile stuck_observable
   ```

Os comandos de análise, benchmark e geração do painel estão no `README.md` e
na documentação em `docs/`.

## Critérios de aceite verificados

| Critério | Resultado |
|---|---|
| Configuração Docker válida | Aprovado por `docker compose config --quiet`. |
| Mosquitto | Contêiner ativo e saudável em `localhost:1883`. |
| MongoDB | Contêiner ativo e saudável em `localhost:27017`. |
| Testes automatizados | 32 testes aprovados por `python -m unittest`. |
| Compilação dos módulos Python | Aprovada por `python -m compileall -q src`. |
| Persistência dual | Validada com 110.050 mensagens em cada coleção. |
| Análise e visualização | Benchmark, métricas multianomalia e painel HTML gerados localmente. |

## Arquivos que não devem ser versionados

O `.gitignore` protege `.env`, ambientes virtuais, dados dos volumes Docker e
`artifacts/`. Portanto, senhas, dados do MongoDB e resultados específicos da
máquina não fazem parte da entrega versionada. O arquivo `.env.example` contém
somente valores de desenvolvimento e deve ser mantido como modelo de
configuração.

## Limites conhecidos

Este é um protótipo acadêmico local. Autenticação MQTT, TLS, retenção,
observabilidade, implantação remota, carga concorrente e calibração dos
detectores em dados industriais reais não estão incluídos no escopo. Esses itens
devem ser tratados como evolução de produção, conforme a conclusão técnica.

## Fechamento de versão no Git

Antes de enviar a entrega, revise as alterações e então execute:

```powershell
git status
git add README.md docs src tests docker-compose.yml requirements.txt .env.example .gitignore
git commit -m "feat: conclui protótipo IIoT e análise técnica"
git push origin main
```

O `git add` não inclui `.env` nem `artifacts/`, pois ambos permanecem ignorados.
