---
title: "WoW Great Vault — Simulador Estatístico"
date: 2026-04-17
updated: 2026-04-17
author: Bruno Pikler
version: 3.0
tags:
  - estatistica
  - monte-carlo
  - markov
  - python
  - wow
  - otimizacao
  - coupon-collector
  - multi-character
  - cli-interativo
type: documentacao-tecnica
status: validado
related:
  - "[[Coupon Collector Problem]]"
  - "[[Programacao Dinamica]]"
  - "[[Monte Carlo]]"
  - "[[Cadeias de Markov]]"
---

# WoW Great Vault — Simulador Estatístico

## Contexto

Decisão semanal no The Great Vault: investir 30, 150 ou 300 minutos para abrir 1, 2 ou 3 slots de loot, sabendo que só posso escolher **1 item por semana** e que itens repetidos (já equipados) são desperdiçados.

**Pergunta central:** dado k itens já coletados e W semanas restantes, qual estratégia minimiza tempo total mantendo trade-off razoável de coleção?

## Modelo matemático

### Premissas

- 18 itens distintos no pool
- Cada slot é sorteio IID uniforme entre os 18 (slots podem repetir entre si)
- Em cada semana com s slots, ganho 1 item novo com probabilidade `p(k, s) = 1 − (k/18)^s`; caso contrário, semana perdida

### Cadeia de Markov

O número de itens k segue uma cadeia de Markov:

```
P(k → k+1) = 1 − (k/18)^s
P(k → k)   = (k/18)^s
```

E[itens após W semanas] **não tem fórmula fechada simples** (a probabilidade é não-linear em k para s≥2). Computa-se por propagação de distribuição:

```
P_{w+1}[k] = P_w[k] · (1 − p_k) + P_w[k−1] · p_{k−1}
```

> [!warning] Erro comum
> A fórmula `18 × (1 − (17/18)^(W·s))` só vale se você acumulasse **todos** os sorteios. Como a regra é "escolhe 1 por semana", essa fórmula **superestima** E[itens] para s≥2 em ~1.2 itens (e superestima P(completar) drasticamente).

### Programação Dinâmica para política ótima adaptativa

`V(k, w) = max_s [ −λ · T(s) + p_s · V(k+1, w−1) + (1 − p_s) · V(k, w−1) ]`

- Terminal: `V(k, 0) = k`
- λ é o "shadow price" do tempo
- λ=0 → maximiza só itens; λ alto → minimiza só tempo

## Resultados validados (k=0, W=22, 10k simulações)

### Estratégias fixas

| s | Tempo | E[itens] (MC) | E[itens] (Markov) | P(completa) |
|---|-------|---------------|-------------------|-------------|
| 1 | 660 min | 12.90 | 12.88 | 0.0% |
| 2 | 3.298 min | 15.28 | 15.28 | 1.5% |
| 3 | 6.571 min | 16.34 | 16.36 | 10.5% |

### Estratégia adaptativa (DP, λ=0.0005)

- E[itens]: **15.67**
- Tempo: **3.472 min**
- Política: começa com s=1 (semanas iniciais, k baixo), escala s conforme k cresce e tempo encolhe

### Custo marginal por item ganho

| Transição | Δ tempo | Δ itens | min/item |
|-----------|---------|---------|----------|
| 0 → 22× s=1 | +660 | +12.9 | 51 |
| 22× s=1 → 22× s=2 | +2.640 | +2.4 | 1.100 |
| 22× s=2 → adaptativo | +174 | +0.4 | 446 |
| adaptativo → 22× s=3 | +3.099 | +0.7 | 4.491 |

## Como rodar

### Requisitos

```bash
pip install numpy
```

Recomendado usar venv: ver [[#Setup com virtual environment]] no fim do doc.

### Comportamento inteligente automático

O script agora **detecta automaticamente**:

- **Hoje** via `date.today()` — não precisa informar a data atual
- **Próxima terça** (reset hard-coded) — calcula a partir de hoje (se hoje for terça, considera hoje)
- **Modo interativo** — se você rodar sem args essenciais, ele pergunta passo a passo

### Modo interativo (default)

Basta rodar sem nada:

```powershell
python "Simulador estatistico.py"
```

O script vai mostrar a data de hoje + próxima terça calculada, e perguntar:

1. **Como informar o tempo restante?**
   - Opção [1]: Data do fim da season (formato `DD/MM/YYYY` ou `YYYY-MM-DD`)
   - Opção [2]: Número de semanas restantes diretamente
2. **Total de itens únicos no pool** (default 18, ENTER aceita)
3. **Personagens** (loop até ENTER vazio):
   - Formato: `nome k` (ex: `paladin 2`)
   - Aceita também `nome:k` (ex: `paladin:2`)
   - Validação: `0 ≤ k ≤ total`

Exemplo de sessão real:

```
Hoje: 17/04/2026 (Friday)
Proximo reset (terca): 21/04/2026

Quanto tempo falta para o fim da season?
  [1] Informar a DATA do fim (DD/MM/YYYY)
  [2] Informar o NUMERO de semanas restantes
Opcao [1]: 1
  Data do fim da season (DD/MM/YYYY): 01/08/2026
  -> 15 semanas (resets) ate o fim da season

Total de itens unicos no pool [18]: [enter]

Adicione seus personagens.
Formato: 'nome k' (ex: 'paladin 2'). ENTER vazio para encerrar.
  char #1: paladin 2
    OK: paladin com k=2
  char #2: warrior 1
    OK: warrior com k=1
  char #3: [enter]
```

### Modo CLI (não-interativo, para automação/n8n)

Passe `--season-end` (ou `--weeks`) **e** `--characters` para pular o prompt:

| Argumento | Tipo | Default | Descrição |
|-----------|------|---------|-----------|
| `--season-end` | data | (interativo) | Data do fim da season — `DD/MM/YYYY` ou `YYYY-MM-DD` |
| `--weeks` | int | (interativo) | Alternativa: número de semanas restantes |
| `--characters` | string | (interativo) | Lista `nome:k,nome:k,...` |
| `--total` | int | `18` | Itens únicos no pool |
| `--sims` | int | `10000` | Simulações Monte Carlo por personagem |
| `--seed` | int | `42` | Seed para reprodutibilidade |
| `--json` | flag | false | Saída JSON estruturada (requer modo CLI completo) |
| `--interactive` | flag | false | Força modo interativo mesmo com args CLI |

### Exemplos CLI

**Cenário atual (paladin k=2, warrior k=1, fim 01/08):**

```powershell
python "Simulador estatistico.py" --season-end 2026-08-18 --characters "paladin:3,warrior:2"
```

**Próxima terça, depois de ganhar +1 item em cada char:**

```powershell
python "Simulador estatistico.py" --season-end 2026-08-18 --characters "paladin:3,warrior:2"
```

**Adicionar terceiro personagem:**

```powershell
python "Simulador estatistico.py" --season-end 2026-08-18 --characters "paladin:3,warrior:2,monk:0"
```

**Informar semanas direto (não precisa data):**

```powershell
python "Simulador estatistico.py" --weeks 15 --characters "paladin:3,warrior:2"
```

**Total customizado (ex: 12 itens em vez de 18):**

```powershell
python "Simulador estatistico.py" --season-end 2026-08-18 --characters "paladin:3" --total 12
```

**Saída JSON para n8n/Power Automate:**

```powershell
python "Simulador estatistico.py" --season-end 2026-08-18 --characters "paladin:3,warrior:2" --json
```

**Mais simulações para reduzir variância MC:**

```powershell
python "Simulador estatistico.py" --season-end 2026-08-18 --characters "paladin:2" --sims 50000
```

### O que o output traz

Para cada personagem o script imprime:

1. **Cabeçalho:** k inicial, % já coletado, semanas restantes
2. **Estratégias fixas** (s=1, 2, 3): E[itens], tempo total, P(completar) — comparando MC vs Markov teórico
3. **Estratégias adaptativas** (vários λ): com a ação ótima para a semana atual
4. **Recomendação consolidada:** qual `s` jogar essa semana (sweet spot λ=0.0005), tempo e P(item novo)

E ao final:

- **Resumo agregado** somando tempo e itens esperados de todos os personagens
- **Lista de ações para a semana imediata** (qual s jogar com cada char)
- **Tempo total da semana** somado entre chars

### Como módulo Python

```python
from datetime import date
import importlib.util

# carrega o modulo (nome com espaco precisa de importlib)
spec = importlib.util.spec_from_file_location("sim", "Simulador estatistico.py")
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)

# helpers de data
proxima_terca = sim.next_tuesday(date.today())
weeks = sim.weeks_remaining(proxima_terca, date(2026, 8, 1))

# estratégia fixa via cadeia de Markov
e_itens, p_complete = sim.markov_stats(s=2, weeks=15, total=18, k_inicial=2)

# política adaptativa
policy, V = sim.solve_optimal_policy(lambda_cost=0.0005, weeks=15, total=18)
acao_essa_semana = int(policy[2, 15])  # k=2, 15 semanas restantes

# análise completa de um personagem
result = sim.analyze_character(
    name='paladin', k_inicial=2, weeks=15,
    total=18, n_sims=10000, seed=42
)
print(result['recommendation_this_week'])
```

### Workflow semanal sugerido

1. **Toda terça pós-reset** (~10h): rode `python "Simulador estatistico.py"` (modo interativo)
2. Informe: data do fim da season + cada char com seu k atualizado
3. Anote a recomendação de `s` para cada personagem (vem em "ACOES PARA A SEMANA")
4. Jogue os 30/150/300 min sugeridos durante a semana
5. Ao final, atualize seu controle (planilha, Notion, etc.) com o k novo se ganhou item

> [!tip] Automação total via n8n
> Plugando o script em uma Azure Function HTTP (modo `--json`), o n8n pode rodar essa rotina automaticamente toda terça e te mandar a recomendação por Slack/email/Notion. Ver seção [[#Integração n8n]] no Notion.

## Validação

- **Cruzamento MC × Markov:** as 3 estratégias fixas batem com erro < 0.1 item (dentro do desvio MC esperado)
- **Sanity check:** s=1 com `p(k,1) = (18−k)/18` é linear, então `E[k_w] = 18 · (1 − (17/18)^w)` vale exatamente — confirmado nos dois métodos
- **Política adaptativa:** começa em s=1 (quando k é baixo, é cheap e quase sempre dá item novo) e escala — comportamento consistente com a teoria

## Referências

- Mitzenmacher & Upfal, *Probability and Computing*, cap. 2 — coupon collector
- Sheldon Ross, *A First Course in Probability* — variáveis geométricas e cadeias de Markov
- [[Coupon Collector Problem]] — Wikipedia: https://en.wikipedia.org/wiki/Coupon_collector%27s_problem
- [[Programacao Dinamica]] — Bellman equation aplicada a problemas de decisão sequencial sob incerteza

## Próximos passos

- [ ] Deploy como Azure Function (HTTP trigger) para integração com n8n
- [ ] Adicionar suporte a múltiplos pools (ex: vault da raid, dungeon, world quests separados)
- [ ] Análise de variância (não só esperança) — qual a P(ter <14 itens) com cada estratégia?
- [ ] Considerar custo de oportunidade do tempo (modelar λ por preferência do usuário)

## Crest accountability

O simulador agora tambem considera crests para transformar item Myth lootado (1/6) em item Myth totalmente maxxado (6/6):

### Track de upgrade — Myth (e so Myth conta)

Itens em WoW podem cair em diferentes tracks de progressao:

- **Adventurer**, **Veteran**, **Champion**, **Hero** — **NAO contam** para esse simulador
- **Myth** — unica track relevante; e a que aparece com o rotulo `Upgrade Level: Myth X/6`

Quando voce informa o `k` de um personagem, conte apenas itens cujo tooltip diz `Myth X/6`. Hero, Champion, etc. ficam de fora.

### Mecanica de crests para itens Myth

- Um item Myth dropa em **1/6** com **item level 272** (na temporada atual)
- Cada upgrade dentro da track Myth (1/6 → 2/6 → ... → 6/6) custa **20 crests**
- Sao 5 upgrades para sair de 1/6 ate o cap **6/6**, totalizando **100 crests** por item totalmente maxxado
- 6/6 e o teto de upgrade do jogo (item mais upgradeavel)

### Geracao de crests por dungeon

- Cada **+12 timed** gera 20 crests
- Pela tabela atual de tempo, `s=1` equivale a 1 dungeon timed, `s=2` a 5 dungeons timed, e `s=3` a 10 dungeons timed
- Portanto `s=2` gera exatamente 100 crests na semana — suficiente para subir 1 item Myth de 1/6 ate 6/6

O output continua mostrando a expectativa de itens lootados, mas adiciona `E[upg 6/6]` e uma estrategia `crest-aware`, que otimiza a expectativa de itens efetivamente upgradeados ate 6/6.

Tambem existe uma estrategia `max loot + crests`, diferente da recomendacao adaptativa normal:

- Primeiro maximiza os itens Myth esperados ate o fim da season.
- Depois maximiza quantos desses itens conseguem ficar 6/6 com crests.
- Por ultimo minimiza o tempo/dungeons entre estrategias equivalentes.

Essa estrategia responde quantas +12 timed voce precisa jogar para perseguir o maximo de loot esperado e ainda ter crests para os upgrades.

Voce pode informar itens ja maxxed (6/6) e crests livres por personagem:

```powershell
python "Simulador estatistico.py" --weeks 15 --characters "paladin:8,warrior:6" --maxxed "paladin:4,warrior:2" --crests "paladin:40,warrior:0"
```

Nesse exemplo, o paladin tem 8 itens Myth lootados (track Myth, ignorando Hero/Champion/etc.), 4 deles ja em 6/6, e 40 crests livres. O warrior tem 6 itens Myth lootados, 2 ja em 6/6, e 0 crests livres.

No modo interativo, informe cada personagem como `nome k maxxed`, por exemplo `paladin 8 4` — onde `k` e a contagem de itens Myth (track Myth, qualquer X/6) e `maxxed` e quantos desses ja estao em 6/6.

## Anexos

- `Simulador estatistico.py` — código fonte com comentários linha a linha
- `azure_function.py` — wrapper HTTP para Azure Functions (integração n8n)
- `requirements.txt` — dependências (numpy, azure-functions)
- `policies.json` — política ótima exportada (gerada com `--json`)

## Setup com virtual environment

Boa prática para Python: isolar dependências por projeto. Evita conflito entre versões de bibliotecas.

```powershell
# 1. cria o venv (uma pasta .venv dentro do projeto)
python -m venv .venv

# 2. ativa o venv (PowerShell)
.\.venv\Scripts\Activate.ps1

# 3. instala dependências
pip install -r requirements.txt

# 4. roda o simulador
python "Simulador estatistico.py"
```

> [!warning] OneDrive + venv
> Se o projeto está dentro do OneDrive, **exclua a pasta `.venv` da sincronização** (botão direito → Configurações OneDrive → Excluir pasta). Senão o OneDrive vai sincronizar milhares de arquivos pequenos do venv. Melhor ainda: mover projetos de código para `C:\Users\bruno\dev\` fora do OneDrive e usar Git para versionamento.

> [!tip] Configurar VSCode
> `Ctrl+Shift+P` → "Python: Select Interpreter" → escolher o que tem `.venv` no caminho. Daí qualquer terminal aberto no VSCode já ativa o venv automaticamente.
