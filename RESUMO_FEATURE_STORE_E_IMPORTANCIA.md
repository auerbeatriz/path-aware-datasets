# Resumo — Feature Store e Análise de Feature Importance

Este documento resume a *feature store* construída a partir dos conjuntos de
dados `datasets/D1` a `D4` (e suas variantes `b`) e os resultados da análise
de importância de features para a previsão da rota de menor latência
(`melhor_rota`), realizada em `Feature_Store_Datasets.ipynb`.

## 1. Cenários de coleta

A *feature store* é construída separadamente para cada dataset, que
representa um regime distinto de tráfego de fundo na rede:

| cenário | datasets | descrição |
|---|---|---|
| **D1** | `D1`, `D1b` | linha de base, sem tráfego de fundo |
| **D2** | `D2`, `D2b` | tráfego de fundo constante |
| **D3** | `D3`, `D3b` | tráfego de fundo com um fluxo iperf longo |
| **D4** | `D4`, `D4b` | tráfego de fundo com múltiplos fluxos iperf concorrentes |

`D3a` e `D4a` foram excluídos por conterem apenas uma coleta secundária
parcial (sem `eventos.txt`, `banda.bwm`, `rotas.txt` ou `config.json`),
insuficiente para reconstruir a store.

Cada cenário cobre aproximadamente uma hora de coleta contínua (3600–3850 s
úteis por rota), com 4 rotas candidatas (`h11_h61`, `h12_h62`, `h13_h63`,
`h14_h64`) monitoradas simultaneamente.

## 2. Features da feature store

A tabela `consolidado` (grão: run × rota × timestamp) reúne as seguintes
famílias de features, todas derivadas de duas fontes brutas: latência
(RTT medido por `ping`) e banda (utilização de interface capturada pelo
`bwm-ng`).

### 2.1 Métricas instantâneas

| feature | método de construção | potencial preditivo |
|---|---|---|
| `latencia_ms` | RTT medido pelo `ping`, amostrado por segundo | sinal direto de congestionamento fim a fim da rota; define o alvo (`melhor_rota = argmin(latencia_ms)`), portanto vazamento de rótulo — ver Seção 4 |
| `gargalo_Mbps` | menor banda disponível entre as interfaces do caminho (mín. das interfaces do trajeto) | representa o "elo mais fraco" da rota — a banda de um caminho é limitada por seu gargalo, não pela média |
| `banda_media_Mbps` | média da banda disponível entre todas as interfaces do caminho | contexto geral de disponibilidade de banda no trajeto, menos sensível a ruído pontual de uma única interface |
| `util_max_pct` | maior utilização (%) observada entre as interfaces do caminho | sinaliza saturação — interfaces com uso próximo de 100% tendem a introduzir fila e, consequentemente, latência |

### 2.2 Features de janela deslizante (`micro`=5s, `curta`=15s, `longa`=30s)

Cada métrica de latência e banda é também agregada em três janelas
temporais, para capturar tendência recente vs. contexto mais amplo:

| padrão de coluna | método | motivo/potencial |
|---|---|---|
| `latencia_p95_{janela}` | percentil 95 da latência na janela | captura a "pior latência típica", mais robusta a outliers que o máximo |
| `latencia_jitter_{janela}` | desvio padrão da latência na janela | mede instabilidade/variabilidade da rota — rotas com alto jitter podem ser piores mesmo com latência média baixa |
| `latencia_media_{janela}` | média da latência na janela | suaviza ruído de amostra a amostra do RTT |
| `gargalo_min_{janela}` | pior gargalo observado na janela | detecta degradação recente de banda antes que se reflita na média |
| `banda_media_{janela}` | média da banda disponível na janela | tendência de disponibilidade de banda no curto/médio prazo |
| `utilizacao_media_{janela}` | utilização média (0–1) na janela | tendência de saturação — complementa `util_max_pct` (instantâneo) com visão temporal |

A motivação de usar três janelas (5s/15s/30s) é permitir que o modelo escolha
entre reagir rapidamente a mudanças (janela curta) ou usar um sinal mais
estável e menos ruidoso (janela longa), sem impor essa escolha a priori.

### 2.3 Deltas e features cruzadas

| feature | método | potencial |
|---|---|---|
| `latencia_delta_micro_longa` | latência média recente (5s) menos latência média de contexto (30s) | captura *tendência*: uma rota piorando recentemente é diferente de uma rota estável, mesmo com a mesma latência instantânea |
| `banda_delta_micro_longa` | pior gargalo recente (5s) sobre banda média de contexto (30s) | mede a severidade da degradação atual relativa ao "normal" da rota |
| `bdp` (*Bandwidth-Delay Product*) | `gargalo_Mbps × latencia_ms` | estima o volume de dados em trânsito no caminho; combina os dois sinais principais em uma única feature, mas herda o vazamento de `latencia_ms` |

### 2.4 Identificadores e dimensão de rota

Colunas como `run_id`, `rota_id`, `ts_epoch`, `datetime_utc`,
`tempo_relativo_s` e `dataset_id` (chaves/timestamps) e `dim_rota`
(`caminho`, `n_links_sw`, `atraso_cfg_ms` — atributos fixos do caminho) são
mantidas na store para rastreabilidade e análises auxiliares, mas são
excluídas da modelagem de importância por não representarem sinais de rede
em tempo real (ver Seção 4).

## 3. Análise de feature importance

### 3.1 Metodologia

O objetivo do modelo é prever **qual das 4 rotas é a melhor** em um dado
instante — uma pergunta inerentemente **comparativa**. Por isso, os dados são
reestruturados do formato longo (uma linha por rota × timestamp) para o
formato **largo** (*wide*): cada timestamp vira uma única linha, com uma
coluna por combinação `(feature, rota_id)` (`fs.construir_wide`, em
`feature_store/pipeline.py`). Nesse formato, o `RandomForestClassifier` pode
aprender splits do tipo `banda_media_Mbps__h13_h63 > banda_media_Mbps__h11_h61`
— uma comparação genuína entre rotas — em vez de apenas memorizar a faixa de
valores típica de cada rota isoladamente, como ocorria em uma formulação
anterior desta análise que apresentava cada rota em uma linha separada, sem
visibilidade das demais rotas do mesmo instante. Timestamps em que alguma
rota tinha valor ausente em alguma feature são descartados no pivot, pois o
formato largo exige as 4 rotas completas na mesma linha.

`melhor_rota` é excluído do conjunto de features (é o alvo), assim como
`latencia_*` e `bdp` — que definem `melhor_rota` por construção
(`melhor_rota = argmin(latencia_ms)`) e dominariam a importância
trivialmente sem agregar informação (ver Seção 4). Restam **13 features** de
banda/gargalo/utilização, cada uma expandida em 4 colunas (uma por rota) no
formato largo — 52 colunas ao todo.

Um `RandomForestClassifier` foi treinado em split estratificado 80/20 (300
árvores no conjunto geral, 200 por cenário), e a importância de cada feature
foi medida por **dois métodos complementares**:

- **MDI (Mean Decrease in Impurity / importância por impureza)**: calculada
  diretamente do `feature_importances_` do RandomForest durante o treino, a
  partir da redução média de impureza (Gini) em cada split. É rápida (não
  exige computação adicional), mas **enviesada a favor de features de alta
  cardinalidade/variância** — métricas instantâneas tendem a ter mais valores
  distintos que agregados de janela, inflando artificialmente sua importância
  aparente.
- **Importância por permutação**: embaralha cada coluna, uma de cada vez, no
  conjunto de teste e mede a queda de acurácia resultante. É mais custosa
  computacionalmente (requer múltiplas reavaliações do modelo), mas **reflete
  diretamente o impacto real na métrica de interesse**, sendo a referência
  mais confiável quando os dois métodos divergem.

Como cada métrica original aparece 4 vezes no formato largo (uma coluna por
rota), a importância de cada uma delas é agregada somando as 4 colunas
correspondentes, para reportar a importância por **métrica**, não por
`(métrica, rota)`.

Ambos os métodos foram aplicados tanto ao conjunto **geral** (todos os 8
datasets combinados) quanto **separadamente por cenário** (`D1`/`D1b` a
`D4`/`D4b`), permitindo verificar se a importância relativa das features é
estável ou muda conforme o regime de tráfego de fundo.

### 3.2 Acurácia

| cenário | acurácia no teste |
|---|---|
| D1 (baseline) | 0,9937 |
| D2 (tráfego constante) | 0,8617 |
| D3 (iperf longo) | 0,8565 |
| D4 (iperf concorrente) | 0,8569 |
| **Geral (todos os datasets)** | **0,8747** |

O modelo prevê a rota de menor latência com ~87% de acurácia no conjunto
geral, comparando as 4 rotas diretamente no mesmo instante, usando apenas
sinais de banda/gargalo — sem qualquer feature de latência.

### 3.3 Importância por permutação — geral vs. por cenário

| feature | D1 | D2 | D3 | D4 | geral |
|---|---|---|---|---|---|
| `gargalo_min_longa_30s` | -0,0003 | 0,0003 | 0,0194 | 0,0219 | **0,0266** |
| `gargalo_min_curta_15s` | 0,0000 | -0,0025 | 0,0115 | 0,0341 | 0,0221 |
| `banda_media_Mbps` | 0,0000 | 0,0259 | 0,0301 | 0,0225 | 0,0128 |
| `util_max_pct` | 0,0000 | 0,0162 | 0,0200 | 0,0251 | 0,0098 |
| `gargalo_Mbps` | 0,0000 | 0,0183 | 0,0164 | 0,0214 | 0,0095 |
| `gargalo_min_micro_5s` | 0,0000 | 0,0040 | 0,0068 | 0,0093 | 0,0069 |
| `banda_delta_micro_longa` | 0,0000 | 0,0037 | 0,0108 | 0,0113 | 0,0053 |
| `banda_media_longa_30s` | -0,0007 | 0,0031 | 0,0130 | 0,0098 | 0,0050 |
| `utilizacao_media_longa_30s` | 0,0000 | 0,0023 | 0,0118 | 0,0093 | 0,0039 |
| `banda_media_curta_15s` | 0,0000 | -0,0011 | 0,0072 | 0,0139 | 0,0028 |
| `utilizacao_media_curta_15s` | 0,0000 | 0,0011 | 0,0057 | 0,0109 | 0,0013 |
| `utilizacao_media_micro_5s` | -0,0001 | 0,0026 | 0,0048 | 0,0084 | 0,0001 |
| `banda_media_micro_5s` | 0,0000 | -0,0011 | 0,0111 | 0,0093 | -0,0002 |

No conjunto geral, a importância por permutação concentra-se nas features de
gargalo em janela (`gargalo_min_longa_30s`, `gargalo_min_curta_15s`) — mais
que em `banda_media_Mbps`/`gargalo_Mbps` isolados — sugerindo que a
*tendência recente* do gargalo, não apenas seu valor pontual, é o sinal mais
discriminativo quando o modelo pode comparar rotas diretamente.

**Achado mais notável: em D1 (baseline, sem tráfego de fundo), a importância
por permutação de praticamente todas as features fica próxima de zero**,
apesar de a acurácia já ser de 99,4%. Isso indica que, sem tráfego de fundo,
pequenas diferenças estruturais entre rotas — não capturadas por nenhuma
feature candidata — bastam para uma árvore de decisão memorizar a resposta
com poucos splits quase determinísticos, sem depender de forma robusta de
nenhuma feature isolada. Em D2 (tráfego constante) e D3 (iperf longo), a
importância se concentra em `banda_media_Mbps`/`util_max_pct`/`gargalo_Mbps`;
em D4 (iperf concorrente, o cenário mais dinâmico), a importância se desloca
mais para `gargalo_min_{janela}`, coerente com sua natureza intermitente.
Isso confirma que a importância "geral" (todos os datasets combinados) é uma
média que mistura regimes com padrões distintos entre si.

### 3.4 Importância por MDI — geral vs. por cenário

| feature | D1 | D2 | D3 | D4 | geral |
|---|---|---|---|---|---|
| `banda_media_Mbps` | 0,0700 | 0,2431 | 0,1872 | 0,0722 | **0,2172** |
| `util_max_pct` | 0,1182 | 0,1955 | 0,2034 | 0,1131 | 0,1842 |
| `gargalo_Mbps` | 0,0739 | 0,1883 | 0,1898 | 0,0999 | 0,1524 |
| `gargalo_min_longa_30s` | 0,0451 | 0,0407 | 0,0500 | 0,0903 | 0,0555 |
| `gargalo_min_curta_15s` | 0,0549 | 0,0378 | 0,0418 | 0,0994 | 0,0511 |
| `banda_media_micro_5s` | 0,0759 | 0,0384 | 0,0391 | 0,0563 | 0,0509 |
| `gargalo_min_micro_5s` | 0,1330 | 0,0495 | 0,0457 | 0,0783 | 0,0501 |
| `utilizacao_media_micro_5s` | 0,0944 | 0,0393 | 0,0393 | 0,0648 | 0,0491 |
| `banda_media_longa_30s` | 0,0812 | 0,0294 | 0,0427 | 0,0704 | 0,0403 |
| `banda_delta_micro_longa` | 0,0019 | 0,0493 | 0,0460 | 0,0723 | 0,0399 |
| `utilizacao_media_longa_30s` | 0,0853 | 0,0295 | 0,0420 | 0,0615 | 0,0382 |
| `banda_media_curta_15s` | 0,0906 | 0,0298 | 0,0364 | 0,0629 | 0,0363 |
| `utilizacao_media_curta_15s` | 0,0756 | 0,0294 | 0,0366 | 0,0584 | 0,0346 |

`banda_media_Mbps` é a feature dominante por MDI no conjunto geral, com
`util_max_pct` e `gargalo_Mbps` logo atrás. **MDI e permutação divergem
sistematicamente na posição intermediária**: por exemplo,
`gargalo_min_longa_30s` é a feature mais importante por permutação (1º lugar,
geral), mas fica apenas em 4º por MDI — o mesmo viés conhecido do MDI a favor
de features de alta cardinalidade (métricas instantâneas como
`banda_media_Mbps` têm mais valores distintos que agregados de janela,
inflando sua importância aparente por impureza). A permutação, medindo o
impacto real na acurácia, é a referência mais confiável quando os dois
divergem.

Nota-se ainda que, mesmo em D1 (onde a importância por permutação é ~zero
para todas as features), o MDI continua atribuindo importância não-trivial a
quase todas elas — evidência de que o MDI captura padrões de treino que não
se traduzem em ganho real de acurácia no teste.

## 4. Limitações e ressalvas

- **Vazamento no alvo**: `melhor_rota` é função determinística de
  `latencia_ms` por construção, o que motivou excluir `latencia_*` e `bdp`
  do conjunto de features.
- **Vazamento parcial mesmo sem latência**: features de banda no mesmo
  instante (`gargalo_Mbps`, `banda_media_Mbps`) podem carregar parte da mesma
  causalidade que gera a latência mais baixa (ex.: link congestionado eleva
  latência e reduz banda simultaneamente) — a importância observada reflete
  correlação contemporânea, não necessariamente uma relação preditiva
  "antecedente" (isto é, banda medida *antes* de a latência mudar).
- **Comparação entre rotas ainda é contemporânea, não preditiva**: o formato
  largo permite ao modelo comparar as 4 rotas no mesmo instante, mas essa
  comparação ainda usa métricas medidas *no momento presente* — o modelo não
  antecipa qual rota será a melhor com base em informação passada, e sim
  classifica, a posteriori, qual já era a melhor naquele segundo. Uma versão
  preditiva exigiria deslocar o alvo para `melhor_rota(t+H)` (horizonte `H`),
  mantendo `X` estritamente retrospectivo, além de usar um split
  treino/teste temporal em vez de aleatório.
- **Volume por cenário**: cada cenário corresponde a uma única execução de
  ~1 hora, sem repetições que permitam estimar variância entre execuções do
  mesmo regime de tráfego.
- **MDI vs. permutação**: quando os dois métodos divergem, a permutação é a
  referência mais confiável, por medir diretamente o impacto na acurácia.
