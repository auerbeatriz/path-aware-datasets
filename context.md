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

- **`Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb` não foi
  alterado.** Toda a implementação preditiva ficou em
  `Feature_Store_Datasets.ipynb`. O diagnóstico da Seção 4 continua válido
  para aquele notebook.
- **`RESUMO_FEATURE_STORE_E_IMPORTANCIA.md` está desatualizado**: reflete a
  análise contemporânea com `shuffle`, sem os resultados da Seção 9.
- **`n_repeats` baixo** (5 por cenário, 10 no geral) para estimar intervalos
  de confiança das importâncias; as tabelas não reportam desvio-padrão.
- Avaliar se as importâncias contemporâneas por cenário (Seções 7–8, ainda
  com `shuffle`) devem ser recalculadas com split temporal, caso sejam
  usadas na dissertação.
