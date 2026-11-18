# Contexto — Feature Store, Análise de Feature Importance e Limitação Preditiva

Este documento registra o histórico e as conclusões de uma sessão de trabalho
envolvendo três artefatos do projeto:

- `feature_store/pipeline.py`
- `Feature_Store_Datasets.ipynb`
- `RESUMO_FEATURE_STORE_E_IMPORTANCIA.md`
- `Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb`

## 1. Reestruturação da análise de feature importance para formato *wide*

O notebook `Feature_Store_Datasets.ipynb` originalmente comparava rotas em
**formato longo** (uma linha por rota × timestamp), o que fazia o modelo
apenas memorizar a faixa de valores típica de cada rota isoladamente, sem
capacidade de comparação genuína entre rotas do mesmo instante.

A pedido do usuário ("eu gostaria que voce excluisse a analise anterior e
s/o considerasse a que compara efetivamente cada rota"), toda a análise em
formato longo foi removida, mantendo apenas a análise em **formato largo**
(*wide*): cada timestamp vira uma única linha, com uma coluna por combinação
`(feature, rota_id)` — o mesmo layout usado em
`Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb`
(`X = [rota_1, rota_2, rota_3, rota_4]`). Nesse formato, o
`RandomForestClassifier` pode aprender splits do tipo
`banda_media_Mbps__h13_h63 > banda_media_Mbps__h11_h61` — uma comparação
genuína entre rotas.

A função `construir_wide()` foi extraída para `feature_store/pipeline.py`
(reutilizável por qualquer notebook consumidor da store), e a análise por
cenário (`D1`/`D1b` a `D4`/`D4b`) foi reconstruída no novo formato.

### Resultados obtidos (formato wide)

| cenário | acurácia no teste |
|---|---|
| D1 (baseline) | 0,9937 |
| D2 (tráfego constante) | 0,8617 |
| D3 (iperf longo) | 0,8565 |
| D4 (iperf concorrente) | 0,8569 |
| **Geral (todos os datasets)** | **0,8747** |

**Achado mais notável**: em D1 (baseline, sem tráfego de fundo), a
importância por permutação de praticamente todas as features fica próxima
de zero, apesar da acurácia já ser de 99,4% — indício de que, sem tráfego de
fundo, pequenas diferenças estruturais entre rotas (não capturadas por
nenhuma feature candidata) bastam para uma árvore de decisão memorizar a
resposta com poucos splits quase determinísticos, sem depender de forma
robusta de nenhuma feature isolada.

No conjunto geral, a importância por permutação concentra-se nas features de
gargalo em janela (`gargalo_min_longa_30s`, `gargalo_min_curta_15s`), mais
que em `banda_media_Mbps`/`gargalo_Mbps` isolados — sugerindo que a
*tendência recente* do gargalo é o sinal mais discriminativo quando o modelo
pode comparar rotas diretamente. MDI e permutação divergem sistematicamente
na posição intermediária, pelo viés conhecido do MDI a favor de features de
alta cardinalidade.

## 2. Persistência do formato wide na feature store (`feature_store/pipeline.py`)

O usuário questionou por que a feature store persistida em disco continuava
em formato longo, dado que o formato wide passou a ser central para a
análise. A resposta arquitetural foi: pivotar para wide é uma **decisão de
análise**, não de armazenamento — a escolha de quais features incluir e qual
chave usar no pivot varia por consumidor, então o formato longo (`csv/`)
permanece como camada canônica lida por `get_features()`.

Ainda assim, optou-se por (Opção B) persistir também um layout wide completo
como artefato derivado, ao lado dos dois layouts já existentes:

- **`csv/`** — layout longo, canônico, um arquivo por feature group
  (`fg_latencia`, `fg_banda_interface`, `fg_banda_rota`, `consolidado`,
  `dim_rota`).
- **`csv_ml/`** — layout largo legado, compatível com `datasets/D*`, cobrindo
  apenas `latencia_ms` e `gargalo_Mbps`.
- **`csv_wide/features_wide.csv`** (novo) — layout largo completo, com
  **todas** as features numéricas de `consolidado`, gerado via
  `fs.construir_wide()` dentro de `exportar_csv()`.

Foi necessário `importlib.reload(fs)` no notebook para que o kernel picasse
as mudanças em `pipeline.py` sem reiniciar — esse reload foi mantido
permanentemente na célula de imports. Todos os 8 datasets (`D1`, `D1b`,
`D2`, `D2b`, `D3`, `D3b`, `D4`, `D4b`) foram reconstruídos com sucesso,
cada um agora com 9 arquivos (5 em `csv/`, 3 em `csv_ml/`, 1 em
`csv_wide/`).

## 3. Atualização de `RESUMO_FEATURE_STORE_E_IMPORTANCIA.md`

O documento de resumo foi reescrito para refletir a análise atual (formato
wide), removendo:
- A variante "com latência vs. sem latência" (obsoleta, pertencia à análise
  em formato longo anterior).
- Referências a imagens PNG que não são mais geradas pelo notebook atual.

E adicionando:
- Tabela de acurácia por cenário (formato wide).
- Tabelas de importância por permutação e por MDI, geral vs. por cenário,
  com os valores reais extraídos das saídas executadas do notebook.
- Uma nova ressalva na Seção 4 (Limitações): "Comparação entre rotas ainda é
  contemporânea, não preditiva".

## 4. Análise: o modelo consegue prever o futuro?

Pergunta do usuário: analisar `Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb`
e verificar se ele testa/prevê o futuro.

**Conclusão: não, em nenhuma das variações de experimento do notebook.**

### 4.1 Pipeline principal (X/y do próprio dataset)

```python
X = np.hstack([temporal_features, latencia_por_rota])
y = rotulos
...
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=1234, shuffle=True, stratify=None
)
```

Dois problemas identificados:
1. **`X` e `y` vêm do mesmo instante**: `y = rotulos = argmin(latência)`
   calculado no mesmo timestamp cujas features alimentam `X`. O modelo
   classifica, a posteriori, qual rota já era a melhor naquele segundo — não
   antecipa nada.
2. **`shuffle=True` no `train_test_split`**: embaralha os timestamps
   aleatoriamente antes de separar treino/teste, misturando "passado" e
   "futuro" nos dois conjuntos. Isso não é um teste de generalização
   temporal — é uma validação i.i.d. que viola a ordem cronológica (o
   modelo pode treinar em `t=1000` e testar em `t=500`).

### 4.2 "Testes manuais" (`nova_latencia/60min_streaming_simultaneo`, fatias por `begin`/`end`)

Testam o modelo treinado em uma coleta diferente ou em fatias diferentes do
mesmo dataset — isso avalia **generalização entre execuções/cenários**, não
previsão temporal. Dentro de cada teste, X e y continuam sendo do mesmo
instante.

### 4.3 Reprodução da Tabela 2 do artigo (generalização cross-dataset D1→D2/D3/D4)

```python
def carregar_X_y(dataset, ...):
    ...
    # y sempre vem de rotulos_h1_h6.txt (definido como argmin(latencia) no instante)
```

Mesmo padrão: treina em `D1`, testa em `D2`/`D3`/`D4` (ou variantes `b`),
mas **dentro de cada dataset**, X e y são do mesmo instante. Testa se um
modelo treinado em um regime de tráfego generaliza para outro regime — não
se o modelo prevê o estado futuro da rede a partir do estado passado.

### 4.4 Conclusão geral (diagnóstico original)

Nenhuma célula do notebook de análise de modelos desloca o alvo no tempo
(`y(t+H)` com `X` estritamente até `t`), e `shuffle=True` ativamente destrói a
ordem temporal que uma avaliação preditiva exigiria. Toda a comparação, em
ambos os notebooks, era **contemporânea**, não preditiva.

## 5. IMPLEMENTADO: versão preditiva em `Feature_Store_Datasets.ipynb`

As duas pendências da seção anterior foram implementadas (Seção 9 do
notebook). O notebook foi reexecutado por completo.

### 5.1 Novos helpers em `protocolo_temporal.py`

> Os dois helpers nasceram em `feature_store/pipeline.py` e foram movidos para
> `protocolo_temporal.py`, na raiz do projeto, quando a análise de modelos
> (`Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb`) passou a usar o
> mesmo protocolo sem passar pela feature store. `pipeline.py` os reexporta, de
> modo que `fs.deslocar_alvo` e `fs.split_temporal` continuam válidos. O módulo
> comum também traz `preparar_treino_teste` (a composição dos dois),
> `largo_de_csv` (quadro largo a partir de um CSV consolidado por rota) e
> `para_epoch`.

- **`deslocar_alvo(largo, horizonte_s, ...)`** — converte a tarefa em
  preditiva: `y(t)` passa a ser `melhor_rota(t + H)`, preservando o valor
  contemporâneo em `alvo_atual` (necessário para o baseline de persistência).
  O deslocamento usa **casamento explícito de `ts_epoch + H`**, não
  `shift(-H)` posicional: a série tem lacunas, e deslocar N linhas apontaria
  para um instante arbitrário (em H=30s, 270 linhas não têm correspondente e
  são descartadas).
- **`split_temporal(largo, fracao_treino, lacuna_s, ...)`** — corte
  cronológico **por dataset**, com lacuna de `H` segundos entre os blocos
  para que nenhum alvo de treino (observado em `t+H`) caia no teste.

Verificou-se que o sinal do deslocamento está correto e que as features de
`X` são retrospectivas (o `rolling` do pipeline não usa `center=True` nem
shift negativo), de modo que não há vazamento de futuro em `X`.

### 5.2 Resultado A — o `shuffle` valia 8,6 pontos

Mesma tarefa, mesmas features, mesmo modelo; muda só o protocolo:

| protocolo (contemporâneo) | acurácia |
|---|---|
| `shuffle=True` (Seção 8) | 0,8747 |
| split cronológico (`H=0`) | **0,7885** |

Confirmado: o `shuffle=True` era um problema real, não estético. O número
honesto para a tarefa contemporânea é **0,7885**.

### 5.3 Resultado B — capacidade preditiva marginal no agregado

| H | modelo | persistência | ganho |
|---|---|---|---|
| 1 s | 0,7639 | 0,8263 | **−0,062** |
| 5 s | 0,7573 | 0,7470 | +0,010 |
| 15 s | 0,7538 | 0,7456 | +0,008 |
| 30 s | 0,7551 | 0,7401 | +0,015 |
| 60 s | 0,7595 | 0,7595 | 0,000 |

Em `H=1s` o modelo perde para a persistência; nos demais horizontes o ganho
não passa de 1,5 ponto.

### 5.4 Resultado C — o agregado esconde cenários opostos (achado central)

Por cenário, `H=30s`:

| cenário | modelo | persistência | ganho |
|---|---|---|---|
| D1 (baseline) | 0,9919 | 0,9868 | +0,005 |
| D2 (tráfego constante) | 0,7395 | 0,6306 | **+0,109** |
| D3 (iperf longo) | 0,7572 | 0,6686 | **+0,089** |
| D4 (iperf concorrente) | 0,6273 | 0,6812 | **−0,054** |

Contraria a expectativa intuitiva: há sinal preditivo real sob tráfego
**estruturado** (D2/D3), e ganho **negativo** no cenário mais dinâmico (D4),
cuja intermitência é imprevisível nesse horizonte. D4 cancela os ganhos de
D2/D3, explicando o agregado fraco.

Curiosidade relevante: **D4 tem as maiores importâncias de toda a tabela
preditiva** (`utilizacao_media_curta_15s` = 0,039) e o pior ganho — o modelo
depende fortemente dessas features de um modo que não generaliza.

### 5.5 Reestruturação: nunca mais importância só-geral

A pedido do usuário, foram **removidas** a tabela `comparacao_fi` e o gráfico
de barras que mostravam apenas o agregado. Toda importância passa a ser
reportada **por cenário com o geral como série de referência** no mesmo
gráfico. A política está documentada na abertura da Seção 8. Isso vale também
para a nova análise de importância preditiva (Seção 9).

### 5.6 Sobre importâncias negativas

Valores negativos de importância por permutação aparecem em várias tabelas.
Não são erro: a métrica é `acurácia_original − acurácia_permutada`, e pode
ser negativa. Duas causas, com leituras distintas:

1. **Ruído em torno de zero** — quando a importância verdadeira é nula (caso
   de D1), a diferença oscila e cai em negativo metade das vezes. Leitura:
   feature irrelevante, não prejudicial.
2. **Sobreajuste àquela feature** — magnitudes maiores (ex.: −0,009 em D3
   preditivo) indicam relação aprendida no treino que não vale no teste.

Negativos são mais frequentes nas tabelas preditivas, coerente com o split
cronológico expor mudança de regime entre os blocos.

### 5.7 Política sobre as Seções 7–8

O `shuffle=True` foi **mantido deliberadamente** nas Seções 7–8, para
permitir a comparação lado a lado com a Seção 9. Em compensação, foram
inseridos dois avisos em destaque (após a acurácia geral e após a tabela por
cenário) e duas ressalvas na Seção 11.

## 6. Itens pendentes

- ~~**`Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb` não foi
  alterado.**~~ **Resolvido** — o notebook ganhou sua própria seção preditiva,
  descrita na Seção 7. O diagnóstico da Seção 4 segue válido para as seções
  anteriores dele, mantidas de propósito para comparação lado a lado.
- **`RESUMO_FEATURE_STORE_E_IMPORTANCIA.md` está desatualizado**: reflete a
  análise contemporânea com `shuffle`, sem os resultados da Seção 9.
- **`n_repeats` baixo** (5 por cenário, 10 no geral) para estimar intervalos
  de confiança das importâncias; as tabelas não reportam desvio-padrão.
- Avaliar se as importâncias contemporâneas por cenário (Seções 7–8, ainda
  com `shuffle`) devem ser recalculadas com split temporal, caso sejam
  usadas na dissertação.


## 7. Predictive section in `Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb`

Added as a new section at the end of the notebook, titled *Pipeline com
protocolo preditivo*. Nothing above it was changed: the contemporaneous
sections stay as they are so the two protocols can be read side by side.

What the section does, in order:

1. Imports `protocolo_temporal` from the project root (Section 8).
2. Builds the wide frame of a dataset with `construir_largo`, which resolves
   file names, joins features and target, and warns about degenerate features.
3. Reports the class distribution of the target over the whole series, the
   training block and the test block.
4. Trains the same seven classifiers of the notebook, now with `StandardScaler`
   in the pipeline, over a sweep of horizons `H ∈ {0, 1, 5, 15, 30, 60}`.
5. Validates with `TimeSeriesSplit` inside the training block instead of the
   shuffled `StratifiedKFold`.
6. Produces the confusion matrices of every model in a single figure, and a
   pruning study of the three tree models.

Two switches drive the whole section:

- `METRICA_PRED` — `'latencia'` or `'banda'`, which selects the feature CSV and
  the `<metric>__<route>` column prefix shared with the feature store.
- `ALVO_PRED` — `'menor_latencia'` (the label of the paper, from
  `rotulos_h1_h6.txt`) or `'maior_banda'` (from `rotulos_maior_banda.txt`).
  Features and target may come from different metrics, which is the cross-metric
  experiment of the Tabela 2 section.

Features are metric-only. The `temporal_features` (hour, minute, second, day,
month, year) are deliberately left out: under a chronological split they
identify the test block, so the model would learn the clock instead of the
network.

### 7.1 Two baselines, and how to read a result against them

Every evaluation reports, on exactly the same test rows:

- **persistence** — predict that the best route in `t + H` is the best route of
  now, which is the `alvo_atual` column that `deslocar_alvo` preserves. This is
  what a reactive controller already achieves with no model at all.
- **majority class** — always predict the most frequent class *of the training
  block*. Estimating it on the test block would itself be leakage.

The checklist that came out of reading these tables:

1. Check whether the dominant class is the same in both blocks. If it is not,
   the majority baseline stops measuring imbalance and starts measuring the
   regime shift between the periods.
2. Convert differences into number of instants, not percentage points.
3. Compare in pairs, counting only the rows where the two predictors disagree
   (McNemar). Otherwise there is no way to tell a real gain from noise.
4. Look at which classes the model actually predicts. `recall_macro` equal to
   `1/n_classes` is the signature of a model that collapsed onto one class.
5. Only claim predictive capability when the model beats **both** baselines.

Worked example, D2 at `H=1s`: SVC reaches 0.7233 against 0.6767 for persistence
and 0.7137 for the majority class. The gain over persistence is 34 instants out
of 730 and survives a paired test (p = 0.01); the gain over the constant
predictor is 7 instants and does not (p = 0.14). The model reproduces the
dominant class, and persistence has a *higher* F1-macro (0.387 against 0.254)
because it at least predicts the minority routes.

## 8. `protocolo_temporal.py` — the shared module

`deslocar_alvo`, `split_temporal` and `para_epoch` were moved out of
`feature_store/pipeline.py` into `protocolo_temporal.py` at the project root,
which also holds `preparar_treino_teste` (the composition of the first two),
`largo_de_csv`, `colunas_de_feature` and the metric prefixes. `pipeline.py`
re-exports all of them, so `fs.deslocar_alvo` and friends keep working and no
cell of the feature-store notebooks had to change.

The contract between both consumers is a single wide frame: one row per instant,
with a group key (`dataset_id`), a time key (`ts_epoch`), one column per route
and the target. The feature store builds it with `pipeline.construir_wide`; the
model-analysis notebook builds it with `largo_de_csv`.

### 8.1 Bandwidth and latency are one second apart

`banda_rotas_h1_h6.csv` starts exactly **one second before**
`latencia_rotas_h1_h6.csv` in all eight four-route datasets, and latency ends
one second later in D2b, D4 and D4b. Since `rotulos_h1_h6.txt` has one line per
latency row, pairing bandwidth rows with that label **by position** shifts every
label by one second.

This is worse than it sounds: in D2b, D4 and D4b both files have the *same* row
count (3650, 3851, 3770), so no truncation warning would appear. Measured on D2,
a positional join disagrees with the correct one on **19.7%** of the rows, and
combined with `deslocar_alvo(H)` the models would be predicting `H+1` seconds
ahead while the tables reported `H`.

`construir_largo` therefore joins by timestamp whenever features and target come
from different metrics, and pairs row by row only when they share the same
source CSV — with `tolerancia_borda=0`, so a label file that no longer matches
its CSV fails loudly instead of being silently truncated. The common grid gives
D1 3599, D1b 3599, D2 3660, D2b 3649, D3 3663, D3b 3658, D4 3850 and D4b 3769
instants.

## 9. Findings the protocol exposed

### 9.1 The aggregate hides a regime shift (D4, D4a)

In D4 the dominant route changes between blocks: route 3 holds 53.94% of the
training block and route 4 holds 71.66% of the test block. The majority-class
baseline is therefore 0.2629, and the model's 0.7289 looks like a large gain
when it is essentially the share of the test block's own dominant route
(0.7234). The only claim that survives is the 8.6 points over persistence
(0.6431). D4a repeats the pattern with two routes.

### 9.2 In D4 the target is decided by a near tie

Routes 3 and 4 have the same latency floor, around 21 ms, but very different
volatility: standard deviation 5.8 ms against 65.7 ms. The per-instant
difference has median +0.89 ms in favour of route 4, and |difference| stays
under 5 ms in 52.7% of the instants. Route 3 only wins when route 4 spikes, and
those spikes are short: the best route changes every 6.4 seconds on average,
with a median run of 3 seconds and 177 runs of exactly one second.

Consequence: when the tree models predict route 3 they are wrong two thirds of
the time, because in the near-tie band route 4 is the answer in 90.7% of the
instants. What distinguishes the two routes is not their level but their
variance, and variance is invisible in a single-instant snapshot. This is the
argument for bringing the window features of `pipeline.py` into this notebook.

### 9.3 Pruning the tree models buys accuracy by giving up classes

With scikit-learn defaults the trees are unpruned, and on D2 with 2905 training
rows and four features the decision tree reaches depth 33 and 590 leaves, the
extra-trees 1246 leaves per tree. Pruning raises accuracy monotonically up to
**exactly** the majority baseline (0.7151) while `classes_predicted` falls to 1
and F1-macro falls from 0.241 to 0.209. `recall_macro` pins at 0.2500, which is
`1/4`: a constant predictor has recall 1 on its class and 0 on the other three.

Per-class recall makes the trade explicit. In D2 at `H=30` route 2 (4 instants)
is never recovered by any of the 21 configurations, route 1 peaks at 6 hits out
of 85 and route 3 at 13 out of 109, while route 4 goes from 0.871 to 1.000 as
pruning tightens. The single configuration where pruning helped rather than
collapsed is `min_samples_leaf=3` on the decision tree, which doubles route 3's
recall without losing route 4's.

### 9.4 GaussianNB and the constant feature (D1 with bandwidth)

With bandwidth as features, GaussianNB predicted route 3 on 521 of the 683 test
rows of D1 — 76% — although route 4 is the best route in 99.94% of the instants.
Accuracy 0.2372 against 1.0000 for the other six models. Three links in the
chain:

1. **In D1 the available bandwidth does not vary.** Nothing competes for the
   links, so it stays pinned at capacity: 99.997 Mbps, standard deviation
   0.0003, 16 distinct values in an hour. The variation is rounding noise in the
   seventh significant digit.
2. **`StandardScaler` promotes that noise to unit variance**, dividing by
   0.0003.
3. **Route 3 has two training rows** (a two-second latency spike on route 4),
   identical after standardization. Within-class variance zero, floored by
   scikit-learn at `var_smoothing * max(variance) = 1e-9`, which turns the class
   into a spike centred on the *modal* bandwidth value — shared exactly by 76.3%
   of the test block.

In log space the spike is worth +37.8 against a prior handicap of only −7.26
(`log(2/2856)`), and the quadratic penalty is zero because the test rows sit on
the centre. The class prior is linear in log and cannot compete.

Confirmation: at `H=60` the label shift moves the two route-3 rows to
99.997009 instead of 99.997012, a value shared by only 2.2% of the test block,
and accuracy jumps to 0.9784. Three millionths of a Mbps separate 76% error
from 98% accuracy.

**Two fixes, both implemented, no dataset excluded:**

- `VAR_SMOOTHING_PRED = 5e-2` in the section's `GaussianNB`. Swept from 1e-9 to
  1e-1: 1e-3, 5e-3 and 1e-2 do *not* fix it (accuracy stays at 0.21, the spike
  merely widens); 5e-2 fixes it at every horizon (0.24 → 1.00). The cost falls
  on the `H=0` column, which is the contemporaneous near-identity artefact
  anyway: D4 with latency drops from 0.879 to 0.779 there. At `H > 0` the
  informative datasets move by at most a point, mostly upwards.
- A **variance diagnostic**, not a filter: a feature whose coefficient of
  variation `std/|mean|` falls below `LIMIAR_VARIACAO_PRED = 1e-4` is reported
  as constant up to numerical noise. `construir_largo` warns and
  `relatorio_variacao` tabulates it per dataset. The threshold separates the two
  sides with room to spare: the bandwidth columns of D1 and D1b sit at 3e-6 to
  5e-6, and the least variable column of every other dataset and metric sits at
  2e-3 or above. **Every dataset stays in the experiments**; the report exists to
  interpret a result, not to drop a collection.

## 10. Two-route datasets and the per-flow label

D3a and D4a collect two routes and spell every file with a `_12` suffix
(`latencia_rotas_h1_h6_12.csv`, `banda_rotas_h1_h6_12.csv`,
`rotulos_maior_banda_12.txt`, and the label file is `labels_h1_h6_12.txt` in D3a
but `rotulos_h1_h6_12.txt` in D4a). Both the predictive section and
`gerar_historico_fluxo.py` now resolve those names by globbing the latency CSV
and reading the suffix off it, so nothing downstream assumes four routes or one
spelling.

`gerar_historico_fluxo.py` also accepts dataset names on the command line
(`python3 gerar_historico_fluxo.py D3a D4a`), which is what generated
`historico_telemetria_h1_h6_12.csv` and `rotulos_por_fluxo_12.txt` for those
two: 7320 rows for D3a (3660 instants × 2 flow categories) and 7698 for D4a
(3849 × 2). The tie-break of `desempate_rotulos.py` resolved almost everything
from the past-10 s window, leaving 105 random draws out of 7320 in D3a and 10
out of 7698 in D4a.

The `mice` label matches `argmin(latency)` exactly in both, while `elephant`
matches a naive `argmax(bandwidth)` only 61-62% of the time — which is the
tie-break doing its job, since bandwidth ties on 25-29% of the instants.

Note that the two `_12` bandwidth CSVs are **not** on the complete one-second
grid, unlike the eight four-route ones: D3a is missing 3 seconds and D4a 1
second, and D4a has one empty cell (`banda_h11_h61` at 00:53:52). Nothing
breaks, because the history uses the intersection of timestamps and
`escolher_rota` ignores missing values, but they would need the same
interpolation as the others for parity.

## 11. Stale derived files

Two sets of derived labels predate the current consolidated CSVs and no longer
match them. They were generated before the bandwidth CSVs were regenerated with
interpolation and, more importantly, before negative available bandwidth was
clipped at zero — which changes *which* route holds the maximum.

| file | current | regenerated | lines that change |
|---|---|---|---|
| `rotulos_maior_banda.txt` (8 datasets) | 1 to 5 lines short | matches the CSV exactly | 222 to 1933 |
| `rotulos_por_fluxo.txt` (8 datasets) | 2 to 10 lines short | matches the CSV exactly | 715 to 2874 |

The 22 missing lines across the bandwidth labels are exactly the 22 seconds the
interpolation filled. Re-running `gerar_rotulos_banda.py` and
`gerar_historico_fluxo.py` fixes both, and was verified in a scratch copy
without touching `datasets/`. This has **not** been done in the repository yet:
it changes up to half the lines of a label file, which would silently invalidate
any stored result that used them.

Until it is, `construir_largo` refuses to load a stale label file rather than
truncating it, which is what `tolerancia_borda=0` is for.
