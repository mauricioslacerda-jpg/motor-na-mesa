# motor-na-mesa

Painel público do motor de daytrade do projeto **Daytrade WIN**, rodando ao vivo sobre o
Ibovespa durante o pregão, com as manchetes do mercado ao lado.

**Painel:** https://mauricioslacerda-jpg.github.io/motor-na-mesa/

## O que é

Um script Python coleta dados públicos, roda o **motor de backtest de verdade** do projeto
e regenera `docs/index.html`. O GitHub Actions executa a cada 10 minutos durante o pregão;
o GitHub Pages serve o HTML. Sem credencial, sem custo por ciclo, com o laptop desligado.

- **Preços:** Yahoo Finance `^BVSP`, candles de 15 min, atraso de ~15 min (declarado no painel).
- **Manchetes:** RSS do InfoMoney, com hora e link.
- **Motor:** `motor/` é **cópia literal** de `src/domain/{entidades,backtest,estrategias}.py` do
  projeto privado. O painel mostra o motor real, não uma reimplementação para demonstração.

## Estrutura

```
coletor.py                 coleta → roda o motor → gera docs/index.html
motor/                     motor vendorizado (cópia literal do projeto)
template.html              o painel; o coletor injeta os dados no lugar de /*{{DADOS}}*/null
docs/index.html            saída publicada pelo Pages
.github/workflows/painel.yml   cron */10 das 08h às 18h BRT, seg–sex
```

## Rodar local

```bash
python coletor.py --forcar    # --forcar ignora a guarda de janela/pregão
```

Sem dependências: só a biblioteca padrão do Python 3.12+.

## Limites declarados

- O Ibovespa à vista **não é** o mini-índice futuro (WIN). Serve para ver o motor funcionando,
  não para aprovar estratégia.
- Amostra curta não aprova nada. A aprovação depende dos gates do projeto: backtest duplo
  concordante, 100 trades em simulador, tetos de risco declarados por escrito.
- **Nenhuma ordem é enviada.** Este repositório não conhece conta, corretora ou credencial.
- O monitoramento se desliga sozinho na data definida em `DATA_FIM` no workflow.

Isto não é recomendação de investimento.
