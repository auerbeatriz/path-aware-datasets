"""Gera o Feature_Store_Datasets.ipynb a partir das celulas definidas aqui.

Constroi, para cada conjunto em datasets/D*, a mesma feature store documentada
em Feature_Store_Telemetria.ipynb, mas usando a fonte de banda desses conjuntos
(um unico banda.bwm cobrindo todas as interfaces, em vez de um banda_raw_rota_*
por rota). O resultado e uma store por dataset, persistida em
feature_store/data/<DATASET>/{csv,csv_ml}.

Manter o notebook sob um gerador evita conflitos de merge no JSON e garante que
a narrativa acompanhe pipeline.py. Executar com:

    .venv/bin/python feature_store/construir_notebook_datasets.py

O texto das celulas markdown segue registro impessoal, adequado a publicacao.
"""

import json

DESTINO = 'Feature_Store_Datasets.ipynb'


def md(texto):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': texto.strip().splitlines(keepends=True)}


def code(texto):
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {},
            'outputs': [], 'source': texto.strip().splitlines(keepends=True)}


CELULAS = [
md(r"""
# Feature Store de Telemetria — `datasets/D*`

Este notebook reconstrói, para **cada conjunto de dados** em `datasets/D*`, a
mesma *feature store* documentada em `Feature_Store_Telemetria.ipynb`. A
diferença está exclusivamente na origem da banda: os relatórios do protótipo
(`prototipo/relatorios`) produzem um `banda_raw_rota_*.csv` por rota, enquanto
cada conjunto em `datasets/` grava um único `banda.bwm`, com o `bwm-ng`
monitorando de uma só vez todas as interfaces do experimento (roteadores e
hosts). `feature_store/pipeline.py` ganhou, para este caso,
`ingerir_banda_arquivo_unico`: filtra apenas as interfaces atravessadas por
alguma rota e replica cada leitura para as rotas que a compartilham — o mesmo
efeito de `ingerir_banda`, partindo de uma fonte diferente.

## Conjuntos processados

| dataset | descrição |
|---|---|
| `D1`, `D1b` | linha de base, sem tráfego de fundo |
| `D2`, `D2b` | tráfego de fundo constante |
| `D3`, `D3b` | tráfego de fundo com um fluxo iperf longo |
| `D4`, `D4b` | tráfego de fundo com múltiplos fluxos iperf concorrentes |

`D3a` e `D4a` foram excluídos: contêm apenas o CSV largo de latência de uma
coleta secundária, sem `eventos.txt`, `banda.bwm`, `rotas.txt` ou `config.json`
— não há como reconstruir a store a partir deles.

## Saída

Para cada dataset `D`, a store é persistida em `feature_store/data/D/`, nos
mesmos três layouts do notebook de referência (longo em `csv/`, largo
compatível com `datasets/D*` em `csv_ml/`, e largo completo com todas as
features em `csv_wide/`). As tabelas em memória de todos os
datasets ficam disponíveis ao final em `resultados`, indexadas pelo nome do
dataset.
"""),

md(r"""
## 1. Importação

Reaproveita a mesma lógica de localização da raiz do projeto usada no notebook
de referência, necessária porque os caminhos relativos empregados
(`datasets/D*`) dependem do diretório de inicialização do kernel.
"""),

code(r"""
import os
import sys
from pathlib import Path


def raiz_do_projeto(marcadores=('prototipo', 'feature_store', 'datasets')):
    candidatos = [Path.cwd(), *Path.cwd().parents]
    for candidato in candidatos:
        if all((candidato / marcador).is_dir() for marcador in marcadores):
            return candidato
    raise RuntimeError(
        f'raiz do projeto não encontrada a partir de {Path.cwd()}. '
        f'Esperado um diretório contendo {marcadores}.'
    )


RAIZ = raiz_do_projeto()
os.chdir(RAIZ)
if str(RAIZ / 'feature_store') not in sys.path:
    sys.path.insert(0, str(RAIZ / 'feature_store'))

print(f'raiz do projeto : {RAIZ}')
print(f'interpretador   : {sys.executable}')
print(f'python          : {sys.version.split()[0]}')
"""),

code(r"""
import glob
import importlib

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

import pipeline as fs
importlib.reload(fs)

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 80)

print(f'pandas {pd.__version__} | numpy {np.__version__}')
"""),

md(r"""
## 2. Descoberta dos datasets

Um dataset é elegível quando dispõe simultaneamente de `banda.bwm`,
`eventos.txt`, `rotas.txt` e `config.json` — os quatro insumos exigidos por
`fs.construir`.
"""),

code(r"""
def dataset_elegivel(pasta):
    exigidos = ['banda.bwm', 'eventos.txt', 'rotas.txt', 'config.json']
    return all(os.path.exists(os.path.join(pasta, arquivo)) for arquivo in exigidos)


todas_as_pastas = sorted(glob.glob('datasets/D*'))
datasets = [os.path.basename(p) for p in todas_as_pastas if dataset_elegivel(p)]
descartados = [os.path.basename(p) for p in todas_as_pastas if not dataset_elegivel(p)]

print(f"datasets elegíveis  ({len(datasets)}): {datasets}")
print(f"datasets descartados ({len(descartados)}): {descartados}")
"""),

md(r"""
## 3. Construção da store por dataset

`fs.construir` recebe `arquivo_banda` apontando para o `banda.bwm` do dataset,
o que roteia a ingestão para `ingerir_banda_arquivo_unico` em vez de
`ingerir_banda`. `pasta_relatorios` e `caminho_config` apontam para a própria
pasta do dataset, de onde vêm `eventos.txt`, `rotas.txt` e `config.json`.

A tolerância de separação de execuções (`gap_maximo_s`) é maior que o padrão
usado em `prototipo/relatorios`: o `banda.bwm` acumula, em uma única coleta
contínua, lacunas isoladas de 1–2 s por amostras perdidas do `bwm-ng`, que a
tolerância padrão de 1 s fragmentaria indevidamente em execuções distintas.
`inferir_alinhamento` já aplica 5 s automaticamente quando `arquivo_banda` é
informado.
"""),

code(r"""
resultados = {}
falhas = {}

for dataset in datasets:
    pasta = f'datasets/{dataset}'
    try:
        resultado = fs.construir(
            pasta_relatorios=pasta,
            caminho_config=f'{pasta}/config.json',
            pasta_destino=f'feature_store/data/{dataset}',
            arquivo_banda=f'{pasta}/banda.bwm',
        )
        resultados[dataset] = resultado
    except Exception as erro:
        falhas[dataset] = erro

print(f"{'dataset':8s} {'residuo_s':>9s} {'registros':>10s} {'rotas':>6s} {'lat. preenchida':>16s}")
print('-' * 60)
for dataset, resultado in resultados.items():
    view = resultado['view']
    al = resultado['alinhamento']
    print(f"{dataset:8s} {al['residuo_s']:9.1f} {len(view):10d} "
          f"{view.rota_id.nunique():6d} {view.latencia_ms.notna().sum():7d}/{len(view):<7d}")

if falhas:
    print()
    print("falhas:")
    for dataset, erro in falhas.items():
        print(f"  {dataset}: {erro}")
"""),

md(r"""
## 4. Persistência

`fs.construir` já persiste cada store em `feature_store/data/<dataset>/`
(parâmetro `pasta_destino`), nos mesmos dois layouts do notebook de
referência. A célula seguinte apenas lista o que foi gravado.
"""),

code(r"""
for dataset in resultados:
    pasta = f'feature_store/data/{dataset}'
    arquivos = sorted(
        glob.glob(f'{pasta}/csv/*.csv')
        + glob.glob(f'{pasta}/csv_ml/*')
        + glob.glob(f'{pasta}/csv_wide/*')
    )
    total_bytes = sum(os.path.getsize(a) for a in arquivos)
    print(f"{dataset}: {len(arquivos)} arquivos, {total_bytes:,} bytes em {pasta}/")
"""),

md(r"""
## 4.1 Arquivos de output e significado das features

### Arquivos gerados por dataset

Para cada `feature_store/data/<DATASET>/`, o pipeline grava três layouts:

**Layout longo** (`csv/`) — um arquivo por feature group, grão explícito na chave:

| arquivo | grão | conteúdo |
|---|---|---|
| `fg_latencia.csv` | (run, rota, ts) | RTT medido por ping |
| `fg_banda_interface.csv` | (run, rota, interface, ts) | taxa e utilização por interface |
| `fg_banda_rota.csv` | (run, rota, ts) | gargalo e agregados do caminho |
| `consolidado.csv` | (run, rota, ts) | junção, features de janela, deltas e alvo — a tabela principal |
| `dim_rota.csv` | (rota) | atributos fixos do caminho (dimensão) |

**Layout largo legado** (`csv_ml/`) — compatível com `datasets/D*`, uma coluna por rota, apenas latência e gargalo:

| arquivo | conteúdo |
|---|---|
| `latencia_rotas_h1_h6.csv` | latência (ms) de cada rota, uma coluna por rota, indexado por `timestamp` |
| `banda_rotas_h1_h6.csv` | gargalo (Mbps) de cada rota, mesmo layout |
| `rotulos_h1_h6.txt` | índice (base 1) da rota de menor latência em cada instante |

**Layout largo completo** (`csv_wide/`) — mesma ideia do `csv_ml/`, mas com
**todas** as features numéricas de `consolidado` (não apenas latência e
gargalo), gerado por `fs.construir_wide`:

| arquivo | grão | conteúdo |
|---|---|---|
| `features_wide.csv` | (ts_epoch) | uma linha por timestamp, uma coluna por combinação `(feature, rota_id)`, mais `melhor_rota` |

Este é o layout usado na Seção 8 para a análise de *feature importance* com
comparação real entre rotas — persistido aqui como artefato derivado, útil
para quem quiser consumir a store fora deste notebook sem reimplementar o
pivot. `get_features` (formato longo) continua sendo o caminho de leitura
recomendado quando é preciso filtrar rotas/métricas/janela antes de pivotar.

### Significado das colunas de `consolidado`

**Chaves e identificadores**

| coluna | significado |
|---|---|
| `run_id` | identificador da execução válida dentro do dataset (após resolução do alinhamento) |
| `rota_id` | caminho de rede ao qual a observação pertence (`h11_h61`, `h12_h62`, `h13_h63`, `h14_h64`) |
| `ts_epoch` | instante da observação, em segundos Unix, na escala comum de banda e latência |
| `datetime_utc` | mesmo instante, em formato de data/hora |
| `tempo_relativo_s` | segundos decorridos desde o início da coleta (uso em gráficos, não em junções) |

**Métricas instantâneas**

| coluna | significado |
|---|---|
| `latencia_ms` | RTT medido pelo ping naquele segundo; `NaN` quando o ping não respondeu |
| `gargalo_Mbps` | banda disponível na interface mais congestionada do caminho — limita a vazão útil da rota |
| `banda_media_Mbps` | média da banda disponível entre todas as interfaces do caminho |
| `util_max_pct` | maior utilização (%) observada entre as interfaces do caminho |

**Features de janela deslizante** (janelas `micro`=5s, `curta`=15s, `longa`=30s)

| padrão de coluna | significado |
|---|---|
| `latencia_p95_{janela}` | pior latência típica na janela (percentil 95) |
| `latencia_jitter_{janela}` | desvio padrão da latência na janela — instabilidade |
| `latencia_media_{janela}` | latência média suavizada na janela |
| `gargalo_min_{janela}` | pior gargalo observado na janela |
| `banda_media_{janela}` | banda média disponível na janela |
| `utilizacao_media_{janela}` | utilização média (0–1) na janela |

**Deltas e features cruzadas**

| coluna | significado |
|---|---|
| `latencia_delta_micro_longa` | tendência: latência média recente (5s) menos a média de contexto (30s) |
| `banda_delta_micro_longa` | severidade do gargalo atual: pior gargalo recente (5s) sobre banda média de contexto (30s) |
| `bdp` | *Bandwidth-Delay Product* (`gargalo_Mbps × latencia_ms`) — volume estimado de dados em trânsito |

**Alvo**

| coluna | significado |
|---|---|
| `melhor_rota` | índice (base 1) da rota de menor latência naquele instante; **função determinística da latência** (vazamento de rótulo, ver Seção 8) |

**Dimensão da rota** (`dim_rota`, incluída apenas com `incluir_dim_rota=True`)

| coluna | significado |
|---|---|
| `caminho` | sequência de switches/hosts percorrida pela rota |
| `n_links_sw` | número de enlaces inter-switch (proxy de número de saltos) |
| `atraso_cfg_ms` | RTT teórico configurado no TCLink para o caminho |

A coluna adicional `dataset_id`, presente apenas no resultado de
`get_features_todos` (Seção 7), identifica de qual dataset (`D1`, `D2` etc.)
cada linha se origina — não existe nos CSVs individuais de cada store.
"""),

md(r"""
## 5. Verificação

Reaplica, para cada dataset, as verificações estruturais do notebook de
referência (Seção 10): ausência de colunas integralmente nulas, contagem
consistente de rotas e concentração dos valores ausentes de latência na
inicialização do ping.
"""),

code(r"""
for dataset, resultado in resultados.items():
    view = resultado['view']

    assert not [c for c in view.columns if view[c].isna().all()], \
        f'{dataset}: há coluna integralmente nula'

    # As contagens por rota podem diferir por poucos segundos: cada rota tem
    # sua propria janela de amostragem de banda, e amostras isoladas do
    # bwm-ng podem faltar em uma interface e nao em outra. Verifica-se
    # proximidade, nao igualdade estrita.
    contagens = view.rota_id.value_counts()
    dispersao = contagens.max() - contagens.min()
    assert dispersao <= 10, \
        f'{dataset}: rotas com contagens muito diferentes de registros: {contagens.to_dict()}'

    ausentes = view[view.latencia_ms.isna()]
    if len(ausentes):
        # As amostras sem latência devem concentrar-se no início da coleta
        # (inicialização do ping), não espalhadas ao longo da série
        limite = view.ts_epoch.min() + 3
        assert ausentes.ts_epoch.max() <= limite, \
            f'{dataset}: valores ausentes de latência fora da inicialização do ping'

print(f"verificações estruturais aprovadas para {len(resultados)} datasets")
"""),

md(r"""
## 6. Visualização de validação

Gargalo e latência ao longo do tempo, lado a lado para todos os datasets, como
checagem visual de que o alinhamento e a agregação produziram séries
coerentes com o cenário de cada coleta (linha de base, tráfego de fundo
constante ou fluxos iperf concorrentes).
"""),

code(r"""
n = len(resultados)
fig, eixos = plt.subplots(n, 2, figsize=(14, 3.2 * n), squeeze=False)

for linha, (dataset, resultado) in enumerate(resultados.items()):
    view = resultado['view']
    ax_banda, ax_latencia = eixos[linha]

    for rota, grupo in view.groupby('rota_id'):
        ax_banda.plot(grupo.tempo_relativo_s, grupo.gargalo_Mbps, label=rota, linewidth=1)
        ax_latencia.plot(grupo.tempo_relativo_s, grupo.latencia_ms, label=rota, linewidth=1)

    ax_banda.set_title(f'{dataset} — gargalo (Mbps)', fontsize=10)
    ax_latencia.set_title(f'{dataset} — latência (ms)', fontsize=10)
    ax_banda.grid(alpha=0.3)
    ax_latencia.grid(alpha=0.3)
    if linha == 0:
        ax_banda.legend(fontsize=8, loc='lower left')

plt.tight_layout()
plt.show()
"""),

md(r"""
## 7. Consulta consolidada entre datasets

Como cada dataset é persistido em sua própria pasta, `get_features` é chamado
uma vez por dataset e as tabelas resultantes são concatenadas com uma coluna
adicional `dataset_id`, permitindo comparações entre coletas sem misturar
`run_id` (que é local a cada store).
"""),

code(r"""
def get_features_todos(datasets=resultados.keys(), **kwargs):
    partes = []
    for dataset in datasets:
        parte = fs.get_features(pasta_origem=f'feature_store/data/{dataset}', **kwargs)
        parte.insert(0, 'dataset_id', dataset)
        partes.append(parte)
    return pd.concat(partes, ignore_index=True)


completo = get_features_todos()
print(f"conjunto completo: {completo.shape[1]} colunas, {len(completo)} registros")
print(f"datasets: {sorted(completo.dataset_id.unique())}")
completo.head()
"""),

md(r"""
## 8. Análise de feature importance (comparação real entre rotas)

O objetivo final do modelo é prever **qual das 4 rotas é a melhor** em um
dado instante — uma pergunta inerentemente **comparativa**. Por isso, os
dados são estruturados no formato **largo** (*wide*): cada timestamp vira uma
única linha, com uma coluna por combinação `(feature, rota_id)` — o mesmo
layout usado em `Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb`
(`X = [rota_1, rota_2, rota_3, rota_4]`). Nesse formato, o RandomForest pode
aprender splits do tipo `banda_media_Mbps__h13_h63 > banda_media_Mbps__h11_h61`
— uma comparação genuína entre rotas — em vez de apenas memorizar a faixa de
valores típica de cada rota isoladamente (o que aconteceria se cada rota
fosse apresentada em uma linha separada, sem as demais rotas do mesmo
instante como contexto).

Como em toda a análise anterior, `melhor_rota` é excluído do conjunto de
features de origem (é o alvo), e as colunas de latência/`bdp` também são
excluídas das features candidatas — `melhor_rota = argmin(latencia_ms)` por
construção (ver Limitações), então mantê-las tornaria a tarefa trivial.
Restam as mesmas 13 features de banda/gargalo/utilização usadas nas versões
anteriores desta análise.

A importância de cada feature é medida por dois métodos complementares:

- **Importância por impureza (MDI)**: `feature_importances_` do RandomForest,
  calculada durante o treino a partir da redução média de impureza (Gini) em
  cada split. É rápida, mas enviesada a favor de features com muitos valores
  distintos e não reflete diretamente o desempenho do modelo.
- **Importância por permutação**: embaralha cada coluna (uma de cada vez) no
  conjunto de teste e mede a queda de acurácia. É mais confiável — reflete o
  impacto real na métrica escolhida — mas mais cara computacionalmente.

Como cada métrica original aparece 4 vezes no formato largo (uma coluna por
rota), a importância de cada uma delas é agregada somando as 4 colunas
correspondentes, para reportar a importância por **métrica**, não por
`(métrica, rota)`.

**Toda importância é reportada por cenário e geral no mesmo gráfico.** A
importância agregada sobre todos os datasets é uma média que mistura quatro
regimes de tráfego com padrões distintos — vista isoladamente, esconde
justamente a variação que interessa (uma feature pode dominar sob tráfego
constante e ser irrelevante na linha de base). O valor geral aparece sempre
como mais uma série ao lado dos cenários, nunca como resultado autônomo.
"""),

code(r"""
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.inspection import permutation_importance

RANDOM_STATE = 1234

COLUNAS_NAO_FEATURE = {
    'dataset_id', 'run_id', 'rota_id', 'ts_epoch', 'datetime_utc',
    'tempo_relativo_s', 'melhor_rota',
}

base = completo.dropna(subset=['melhor_rota']).copy()

candidatas = [c for c in base.columns if c not in COLUNAS_NAO_FEATURE]
candidatas = [c for c in candidatas if not c.startswith('latencia_') and c not in ('bdp',)]
candidatas = [c for c in candidatas if base[c].notna().any()]

print(f"features candidatas: {len(candidatas)}")
print(f"registros (formato longo, antes do pivot): {len(base)}")
"""),

md(r"""
### Reestruturação para o formato largo

`construir_wide` (definida em `feature_store/pipeline.py`, reaproveitável por
qualquer notebook consumidor da store) pivota `base` — uma linha por
`rota_id`/timestamp — para uma linha por timestamp, com uma coluna por
combinação `(feature, rota_id)`.
"""),

code(r"""
base_wide = fs.construir_wide(base, candidatas)

print(f"linhas (timestamps): {len(base_wide)}")
print(f"colunas: {base_wide.shape[1]} ({len(candidatas)} features × 4 rotas + chaves + alvo)")
base_wide.head()
"""),

md(r"""
### Treino do RandomForest

Split treino/teste estratificado (80/20). A importância por impureza (MDI) é
calculada a partir do modelo treinado; a importância por permutação é
calculada sobre o conjunto de teste, para não inflar a métrica com
overfitting.
"""),

code(r"""
colunas_wide = [c for c in base_wide.columns if c not in ('dataset_id', 'ts_epoch', 'melhor_rota')]

X_wide = base_wide[colunas_wide]
y_wide = base_wide['melhor_rota'].astype(int)

X_train_w, X_test_w, y_train_w, y_test_w = train_test_split(
    X_wide, y_wide, test_size=0.2, random_state=RANDOM_STATE, stratify=y_wide
)

modelo_wide = RandomForestClassifier(n_estimators=300, random_state=RANDOM_STATE, n_jobs=-1)
modelo_wide.fit(X_train_w, y_train_w)

acuracia_wide = modelo_wide.score(X_test_w, y_test_w)
print(f"features: {len(colunas_wide)} ({len(candidatas)} métricas × 4 rotas)")
print(f"registros: {len(X_wide)}")
print(f"acurácia no teste: {acuracia_wide:.4f}")
"""),

md(r"""
> ⚠️ **Esta acurácia está inflada e não deve ser citada isoladamente.**
>
> O `train_test_split` acima usa `shuffle=True` (exigido por `stratify`), que
> sorteia instantes individualmente: o segundo `t` pode ir para o treino e o
> segundo `t+1` para o teste. Numa série amostrada a cada segundo essas duas
> linhas são quase o mesmo vetor — o teste passa a conter quase-duplicatas do
> treino, e a métrica mede, em parte, memorização.
>
> A **Seção 9** repete esta tarefa trocando apenas o protocolo de avaliação
> (split cronológico) e mede a diferença: **0,8747 → 0,7885**, queda de
> **8,6 pontos** atribuível só ao protocolo. O `shuffle=True` foi mantido aqui
> **deliberadamente**, para tornar essa comparação possível.
"""),

code(r"""
resultado_perm_wide = permutation_importance(
    modelo_wide, X_test_w, y_test_w,
    n_repeats=10, random_state=RANDOM_STATE, n_jobs=1
)

importancia_perm_wide = pd.Series(resultado_perm_wide.importances_mean, index=colunas_wide)
importancia_mdi_wide = pd.Series(modelo_wide.feature_importances_, index=colunas_wide)

# Cada métrica original aparece 4 vezes (uma por rota) — agrega somando a
# importância das 4 colunas, para reportar a importância por métrica (não
# por combinação métrica/rota)
metrica_de = lambda coluna: coluna.rsplit('__', 1)[0]

importancia_perm = importancia_perm_wide.groupby(metrica_de).sum().sort_values(ascending=False)
importancia_mdi = importancia_mdi_wide.groupby(metrica_de).sum().sort_values(ascending=False)

# A importância geral NÃO é exibida isoladamente: é uma média que mistura
# regimes de tráfego com padrões distintos e, sozinha, esconde essa variação.
# Serve apenas como coluna de referência nos gráficos por cenário adiante.
print(f"importância geral calculada para {len(importancia_perm)} métricas "
      f"(exibida junto aos cenários nas células seguintes)")
"""),

code(r"""
print(f"acurácia no teste (shuffle — ver ressalva acima): {acuracia_wide:.4f}")
print("os gráficos de importância aparecem adiante, sempre por cenário + geral")
"""),

md(r"""
### Feature importance por cenário (formato wide)

A análise anterior combina todos os datasets — mas cada par (`D1`/`D1b`,
`D2`/`D2b`, `D3`/`D3b`, `D4`/`D4b`) representa um cenário de tráfego de fundo
distinto (ver "Conjuntos processados"), e a importância relativa das
features pode variar conforme o regime de congestionamento. Esta seção
repete o pivot para o formato largo e o treino **separadamente para cada
cenário**, com o mesmo conjunto de 13 features de banda/gargalo, para
verificar se, por exemplo, o gargalo importa mais sob tráfego concorrente
(`D4`) do que na linha de base (`D1`) — agora com o modelo genuinamente
comparando as 4 rotas em cada instante, não apenas reconhecendo a faixa de
valores típica de cada uma.
"""),

code(r"""
CENARIOS = {
    'D1 (baseline)': ['D1', 'D1b'],
    'D2 (tráfego constante)': ['D2', 'D2b'],
    'D3 (iperf longo)': ['D3', 'D3b'],
    'D4 (iperf concorrente)': ['D4', 'D4b'],
}

importancias_perm_por_cenario = {}
importancias_mdi_por_cenario = {}
acuracias_por_cenario = {}

for nome_cenario, datasets_cenario in CENARIOS.items():
    base_c = base[base.dataset_id.isin(datasets_cenario)]
    base_wide_c = fs.construir_wide(base_c, candidatas)

    colunas_wide_c = [c for c in base_wide_c.columns if c not in ('dataset_id', 'ts_epoch', 'melhor_rota')]
    X_c = base_wide_c[colunas_wide_c]
    y_c = base_wide_c['melhor_rota'].astype(int)

    X_train_c, X_test_c, y_train_c, y_test_c = train_test_split(
        X_c, y_c, test_size=0.2, random_state=RANDOM_STATE, stratify=y_c
    )

    modelo_c = RandomForestClassifier(n_estimators=200, random_state=RANDOM_STATE, n_jobs=-1)
    modelo_c.fit(X_train_c, y_train_c)
    acuracia_c = modelo_c.score(X_test_c, y_test_c)

    resultado_perm_c = permutation_importance(
        modelo_c, X_test_c, y_test_c,
        n_repeats=5, random_state=RANDOM_STATE, n_jobs=1
    )

    perm_c = pd.Series(resultado_perm_c.importances_mean, index=colunas_wide_c)
    mdi_c = pd.Series(modelo_c.feature_importances_, index=colunas_wide_c)

    importancias_perm_por_cenario[nome_cenario] = perm_c.groupby(metrica_de).sum()
    importancias_mdi_por_cenario[nome_cenario] = mdi_c.groupby(metrica_de).sum()
    acuracias_por_cenario[nome_cenario] = acuracia_c

    print(f"{nome_cenario:26s} | timestamps: {len(X_c):6d} | acurácia: {acuracia_c:.4f}")
"""),

md(r"""
### Comparação entre cenários e resultado geral

Tabela com a importância por permutação de cada feature em cada cenário,
lado a lado com a importância geral (todos os datasets combinados),
ordenada pela importância geral.
"""),

code(r"""
comparacao_cenarios = pd.DataFrame(importancias_perm_por_cenario)
comparacao_cenarios['geral (todos os datasets)'] = importancia_perm
comparacao_cenarios = comparacao_cenarios.sort_values('geral (todos os datasets)', ascending=False)

comparacao_cenarios
"""),

code(r"""
fig, ax = plt.subplots(figsize=(11, 6))
comparacao_cenarios.plot.barh(ax=ax, width=0.8)
ax.set_xlabel('Importância por permutação (queda de acurácia)')
ax.set_title('Importância por permutação — por cenário vs. geral (formato wide)')
ax.invert_yaxis()
ax.grid(axis='x', alpha=0.3)
ax.legend(fontsize=8, loc='lower right')
plt.tight_layout()
plt.show()
"""),

md(r"""
### MDI por cenário e resultado geral

Mesma comparação anterior, agora usando a importância por impureza (MDI) em
vez de permutação — permite ver se a divergência entre os dois métodos
observada no resultado geral também aparece dentro de cada cenário
individualmente.
"""),

code(r"""
comparacao_cenarios_mdi = pd.DataFrame(importancias_mdi_por_cenario)
comparacao_cenarios_mdi['geral (todos os datasets)'] = importancia_mdi
comparacao_cenarios_mdi = comparacao_cenarios_mdi.sort_values('geral (todos os datasets)', ascending=False)

comparacao_cenarios_mdi
"""),

code(r"""
fig, ax = plt.subplots(figsize=(11, 6))
comparacao_cenarios_mdi.plot.barh(ax=ax, width=0.8)
ax.set_xlabel('Importância por MDI (redução média de impureza)')
ax.set_title('Importância por MDI — por cenário vs. geral (formato wide)')
ax.invert_yaxis()
ax.grid(axis='x', alpha=0.3)
ax.legend(fontsize=8, loc='lower right')
plt.tight_layout()
plt.show()
"""),

md(r"""
### Acurácia por cenário

A acurácia de cada modelo por cenário, comparada com a acurácia geral obtida
com todos os datasets combinados — indica se a tarefa fica mais fácil ou mais
difícil quando restrita a um único regime de tráfego.
"""),

code(r"""
resumo_acuracia = pd.Series(acuracias_por_cenario)
resumo_acuracia['geral (todos os datasets)'] = acuracia_wide
resumo_acuracia.to_frame('acurácia no teste')
"""),

md(r"""
> ⚠️ **Mesma ressalva do `shuffle=True`**: estas acurácias por cenário — e as
> importâncias por permutação das células anteriores — também foram medidas
> com split embaralhado, sujeitas à mesma inflação de ~8 pontos. A Seção 9
> recalcula **tanto o desempenho quanto as importâncias** por cenário com
> split temporal; use aqueles valores como referência e estes apenas como
> ordenação indicativa.
"""),

md(r"""
## 9. Avaliação preditiva: horizonte `H` e split temporal

Todas as seções anteriores são **contemporâneas**: `X` e `y` vêm do mesmo
instante, e o split 80/20 embaralha os timestamps. Isso responde "qual rota
*já era* a melhor neste segundo?", não "qual rota *será* a melhor daqui a
`H` segundos?".

Esta seção reformula o experimento em duas frentes, que precisam ser
aplicadas **juntas** — deslocar o alvo sem corrigir o split não elimina o
vazamento, porque o embaralhamento coloca instantes vizinhos (quase
idênticos, dada a autocorrelação da série) em treino e teste ao mesmo tempo:

1. **Alvo deslocado**: `y = melhor_rota(t + H)`, com `X` contendo apenas
   informação disponível até `t`. As features de janela do pipeline já são
   todas retrospectivas (`rolling` sobre o passado), então `X` é legítimo
   como "estado observado até agora".
2. **Split temporal**: os primeiros 80% dos instantes de *cada dataset* vão
   para treino, os últimos 20% para teste, com uma **lacuna de `H` segundos**
   entre os blocos, para que nenhum alvo de treino (observado em `t + H`)
   caia dentro da janela de teste.

O deslocamento é feito por casamento explícito de `ts_epoch + H`, não por
`shift(-H)` posicional: a série tem lacunas (segundos sem medida, ou
descartados no pivot por rota incompleta), e deslocar `N` linhas apontaria
para um instante arbitrário.

Dois baselines contextualizam o resultado:

- **persistência** — prever que a melhor rota em `t + H` é a mesma de `t`.
  É o competidor sério: se o modelo não o supera, não aprendeu nada além da
  inércia da série.
- **classe majoritária** — a rota mais frequente no treino. Piso absoluto.
"""),

code(r'''
def avaliar_preditivo(base_longa, colunas_candidatas, horizonte_s,
                      fracao_treino=0.8, n_estimators=300, calcular_permutacao=False):
    """Treina e avalia a previsão da melhor rota em t + horizonte_s.

    Devolve um dicionário com as acurácias do modelo e dos dois baselines,
    além do modelo e dos conjuntos, para inspeção posterior.
    """
    largo = fs.construir_wide(base_longa, colunas_candidatas)

    if horizonte_s > 0:
        largo = fs.deslocar_alvo(largo, horizonte_s)
    else:
        # H = 0: tarefa contemporânea, mas já com split temporal. Serve de
        # referência para isolar o efeito do shuffle. alvo_atual == alvo,
        # então o baseline de persistência dá 1.0 por construção.
        largo = largo.assign(alvo_atual=largo['melhor_rota'])

    treino, teste = fs.split_temporal(
        largo, fracao_treino=fracao_treino, lacuna_s=horizonte_s
    )

    colunas_X = [c for c in largo.columns
                 if c not in ('dataset_id', 'ts_epoch', 'melhor_rota', 'alvo_atual')]

    X = largo[colunas_X]
    y = largo['melhor_rota'].astype(int)

    X_tr, y_tr = X[treino], y[treino]
    X_te, y_te = X[teste], y[teste]

    modelo = RandomForestClassifier(
        n_estimators=n_estimators, random_state=RANDOM_STATE, n_jobs=-1
    )
    modelo.fit(X_tr, y_tr)
    acuracia = modelo.score(X_te, y_te)

    # Baseline de persistência: a melhor rota daqui a H segundos é a de agora.
    # Avaliado exatamente nas mesmas linhas de teste, para ser comparável.
    persistencia = (largo.loc[teste, 'alvo_atual'].astype(int) == y_te).mean()

    # Baseline de classe majoritária: estimado no TREINO, nunca no teste —
    # olhar a distribuição do teste para escolher a classe já seria vazamento.
    classe_majoritaria = y_tr.value_counts().idxmax()
    majoritaria = (y_te == classe_majoritaria).mean()

    resultado = {
        'horizonte_s': horizonte_s,
        'n_treino': len(X_tr),
        'n_teste': len(X_te),
        'acuracia_modelo': acuracia,
        'acuracia_persistencia': persistencia,
        'acuracia_majoritaria': majoritaria,
        'ganho_sobre_persistencia': acuracia - persistencia,
        'modelo': modelo,
        'colunas_X': colunas_X,
        'X_teste': X_te,
        'y_teste': y_te,
    }

    if calcular_permutacao:
        perm = permutation_importance(
            modelo, X_te, y_te, n_repeats=5, random_state=RANDOM_STATE, n_jobs=1
        )
        resultado['importancia_permutacao'] = (
            pd.Series(perm.importances_mean, index=colunas_X)
            .groupby(metrica_de).sum().sort_values(ascending=False)
        )

    return resultado


print('avaliar_preditivo definida')
'''),

md(r"""
### Varredura de horizontes

`H = 0` é incluído como referência: reproduz a tarefa contemporânea das
seções anteriores, mas já **com split temporal**. A diferença entre essa
linha e a acurácia da Seção 8 isola quanto da acurácia original vinha do
`shuffle=True` e quanto da informação de fato presente nas features.

Note que em `H = 0` o baseline de persistência é trivialmente 100% (prever
"a melhor rota agora é a melhor rota agora"), então só as linhas com
`H > 0` têm comparação significativa contra persistência.
"""),

code(r"""
HORIZONTES = [0, 1, 5, 15, 30, 60]

resultados_preditivos = {}

for H in HORIZONTES:
    resultados_preditivos[H] = avaliar_preditivo(base, candidatas, horizonte_s=H)
    r = resultados_preditivos[H]
    print(f"H={H:3d}s | treino={r['n_treino']:6d} teste={r['n_teste']:6d} | "
          f"modelo={r['acuracia_modelo']:.4f} | persistência={r['acuracia_persistencia']:.4f} | "
          f"majoritária={r['acuracia_majoritaria']:.4f}")

tabela_preditiva = pd.DataFrame([
    {
        'horizonte (s)': r['horizonte_s'],
        'modelo': r['acuracia_modelo'],
        'persistência': r['acuracia_persistencia'],
        'classe majoritária': r['acuracia_majoritaria'],
        'ganho sobre persistência': r['ganho_sobre_persistencia'],
        'n treino': r['n_treino'],
        'n teste': r['n_teste'],
    }
    for r in resultados_preditivos.values()
]).set_index('horizonte (s)')

tabela_preditiva
"""),

code(r"""
fig, ax = plt.subplots(figsize=(9, 5))

tabela_preditiva['modelo'].plot(ax=ax, marker='o', label='RandomForest', color='steelblue')
tabela_preditiva['persistência'].plot(ax=ax, marker='s', linestyle='--',
                                      label='baseline: persistência', color='darkorange')
tabela_preditiva['classe majoritária'].plot(ax=ax, marker='^', linestyle=':',
                                            label='baseline: classe majoritária', color='gray')

ax.axhline(acuracia_wide, color='green', linestyle='-.', alpha=0.7,
           label=f'Seção 8 (contemporâneo, shuffle): {acuracia_wide:.3f}')

ax.set_xlabel('Horizonte de previsão H (s)')
ax.set_ylabel('Acurácia no teste')
ax.set_title('Degradação da acurácia com o horizonte de previsão\n(split temporal, sem embaralhamento)')
ax.set_ylim(0, 1.02)
ax.grid(alpha=0.3)
ax.legend(fontsize=9)
plt.tight_layout()
plt.show()
"""),

md(r"""
### O efeito isolado do `shuffle=True`

A questão vale mesmo para a análise **contemporânea** das seções anteriores:
o `train_test_split(..., shuffle=True)` sorteia instantes individualmente,
então o segundo `t` pode ir para o treino e o segundo `t+1` para o teste.
Numa série com forte autocorrelação (a banda de uma rota em segundos
consecutivos é praticamente a mesma), isso equivale a testar o modelo em
cópias quase exatas de exemplos que ele já viu — o teste deixa de medir
generalização e passa a medir, em parte, memorização.

A célula abaixo compara os dois protocolos de avaliação **na mesma tarefa
contemporânea** (`H = 0`, mesmas features, mesmo modelo), mudando apenas
como o conjunto de teste é formado.
"""),

code(r"""
comparacao_protocolo = pd.DataFrame({
    'acurácia no teste': {
        'contemporâneo (H=0), shuffle=True  — Seção 8': acuracia_wide,
        'contemporâneo (H=0), split temporal': resultados_preditivos[0]['acuracia_modelo'],
        f'preditivo (H={HORIZONTES[-1]}s), split temporal': resultados_preditivos[HORIZONTES[-1]]['acuracia_modelo'],
        f'preditivo (H={HORIZONTES[-1]}s), baseline persistência': resultados_preditivos[HORIZONTES[-1]]['acuracia_persistencia'],
    }
})

queda_shuffle = acuracia_wide - resultados_preditivos[0]['acuracia_modelo']
print(f"queda ao trocar shuffle por split temporal (mesma tarefa, H=0): {queda_shuffle:+.4f}")

comparacao_protocolo
"""),

md(r"""
### Feature importance no regime preditivo

A importância da Seção 8 diz quais features explicam a melhor rota *no mesmo
instante*. Aqui a pergunta muda: quais features carregam sinal sobre a melhor
rota **no futuro**?

Como em toda análise de importância deste notebook, o resultado é reportado
**por cenário com o geral ao lado**. Aqui isso é ainda mais necessário: os
ganhos preditivos variam fortemente entre regimes (ver tabela adiante), então
uma importância agregada mediaria situações em que o modelo tem sinal
antecipatório com outras em que não tem.

Diferente das seções anteriores, estas importâncias usam **split temporal**,
então não sofrem a inflação do `shuffle`.
"""),

code(r"""
# Três horizontes representando escalas de decisão distintas na rede.
# Os valores são múltiplos das janelas do pipeline (5s, 15s, 30s), para que o
# horizonte seja comparável ao contexto que as features enxergam:
#   curto  — reação imediata; o estado atual ainda é quase o estado futuro
#   médio  — o horizonte em que um reroteamento reativo faria efeito
#   longo  — além da janela mais longa do pipeline (30s): exige que as
#            features carreguem tendência, não apenas o estado corrente
HORIZONTES_NOMEADOS = {
    'curto (5s)': 5,
    'médio (30s)': 30,
    'longo (120s)': 120,
}

# Mantido para compatibilidade com o texto que referencia o horizonte médio
H_ANALISE = HORIZONTES_NOMEADOS['médio (30s)']

importancias_pred = {}   # (horizonte, cenário) -> Series de importância
resultados_pred = {}     # (horizonte, cenário) -> dict completo

for nome_h, H in HORIZONTES_NOMEADOS.items():
    r_geral = avaliar_preditivo(base, candidatas, horizonte_s=H,
                                calcular_permutacao=True)
    resultados_pred[(nome_h, 'geral (todos os datasets)')] = r_geral
    importancias_pred[(nome_h, 'geral (todos os datasets)')] = r_geral['importancia_permutacao']

    for nome_cenario, datasets_cenario in CENARIOS.items():
        base_c = base[base.dataset_id.isin(datasets_cenario)]
        r_c = avaliar_preditivo(base_c, candidatas, horizonte_s=H,
                                n_estimators=200, calcular_permutacao=True)
        resultados_pred[(nome_h, nome_cenario)] = r_c
        importancias_pred[(nome_h, nome_cenario)] = r_c['importancia_permutacao']

    print(f"{nome_h:14s} | geral: modelo={r_geral['acuracia_modelo']:.4f} "
          f"persistência={r_geral['acuracia_persistencia']:.4f} "
          f"ganho={r_geral['ganho_sobre_persistencia']:+.4f}")

# Referência usada no texto das células seguintes
importancia_perm_preditiva = importancias_pred[(list(HORIZONTES_NOMEADOS)[1],
                                                'geral (todos os datasets)')]
"""),

md(r"""
### Resultado preditivo por cenário

O critério de sucesso **não** é a acurácia absoluta, e sim o **ganho sobre a
persistência** — prever que a melhor rota daqui a `H` segundos é a de agora.
Em cenários estáveis a melhor rota quase não muda e a persistência já acerta
quase sempre, de modo que acurácia alta não é evidência de poder preditivo.

Os resultados abaixo desmentem uma expectativa razoável: a de que o sinal
preditivo apareceria no cenário mais dinâmico. Observa-se o oposto — ganho
substancial sob tráfego **estruturado** (`D2` constante, `D3` iperf longo),
onde a degradação da banda é gradual e portanto antecipável, e ganho
**negativo** em `D4` (iperf concorrente), cuja intermitência é imprevisível
nesse horizonte: ali o modelo fica pior do que não fazer nada. Em `D1` a
persistência satura e sobra pouca margem.

Isso explica o agregado fraco: `D4` cancela os ganhos de `D2`/`D3` — mais um
caso em que o número geral, sozinho, seria enganoso.
"""),

code(r"""
linhas_cenario_pred = []

for nome_cenario, datasets_cenario in CENARIOS.items():
    base_c = base[base.dataset_id.isin(datasets_cenario)]
    r = avaliar_preditivo(base_c, candidatas, horizonte_s=H_ANALISE, n_estimators=200)
    linhas_cenario_pred.append({
        'cenário': nome_cenario,
        'modelo': r['acuracia_modelo'],
        'persistência': r['acuracia_persistencia'],
        'classe majoritária': r['acuracia_majoritaria'],
        'ganho sobre persistência': r['ganho_sobre_persistencia'],
        'n teste': r['n_teste'],
    })

preditivo_por_cenario = pd.DataFrame(linhas_cenario_pred).set_index('cenário')
print(f"horizonte: H={H_ANALISE}s | split temporal por dataset, lacuna de {H_ANALISE}s")
preditivo_por_cenario
"""),

md(r"""
## 10. Resumo e conclusões

### O que foi feito

A análise parte do conjunto consolidado dos 8 datasets elegíveis (`completo`,
Seção 7 — 117.718 registros no formato longo), reestruturado para o formato
largo: cada timestamp vira uma linha, com uma coluna por `(feature, rota_id)`,
permitindo ao RandomForest comparar as 4 rotas diretamente (ex.:
`banda_media_Mbps__h13_h63 > banda_media_Mbps__h11_h61`) em vez de apenas
reconhecer a faixa típica de cada rota isoladamente.

Sobre essa base, foram conduzidos **dois experimentos com perguntas
distintas**:

| | Seções 7–8 (contemporâneo) | Seção 9 (preditivo) |
|---|---|---|
| pergunta | qual rota *era* a melhor neste segundo? | qual rota *será* a melhor em `t+H`? |
| alvo | `melhor_rota(t)` | `melhor_rota(t+H)` |
| split | aleatório estratificado 80/20 | cronológico 80/20, lacuna de `H` |
| baseline | classe majoritária | persistência + classe majoritária |
| status | **limite superior otimista** | **medida honesta** |

### Features eliminadas e motivo

| feature(s) removida(s) | motivo da exclusão |
|---|---|
| `latencia_*` (p95, jitter, média em todas as janelas) e `latencia_ms` | Definem `melhor_rota` por construção (`melhor_rota = argmin(latencia_ms)`), então dominariam a importância trivialmente — ver "Vazamento no alvo" na Seção 11. |
| `bdp` | Calculado como `gargalo_Mbps × latencia_ms`, herda o mesmo vazamento. |
| `dataset_id`, `run_id`, `rota_id`, `ts_epoch`, `datetime_utc`, `tempo_relativo_s` | Identificadores e marcações temporais, não sinais de rede. |
| Timestamps com valor ausente em alguma rota | Descartados no pivot (`dropna`), pois o formato largo exige as 4 rotas completas na mesma linha. |

Restaram **13 features** de origem, cada uma expandida em 4 colunas no
formato largo.

### Resultado 1: o protocolo de avaliação vale ~8,6 pontos

Mantendo a tarefa, as features e o modelo idênticos, e trocando **apenas** a
forma de separar treino e teste:

| protocolo (tarefa contemporânea) | acurácia |
|---|---|
| `shuffle=True` (Seção 8) | 0,8747 |
| split cronológico (Seção 9, `H=0`) | 0,7885 |

A diferença não vem do modelo: vem de o split aleatório colocar segundos
consecutivos — quase idênticos, dada a autocorrelação da série — em treino e
teste simultaneamente. **O número a citar para a tarefa contemporânea é
0,7885**, não 0,8747.

### Resultado 2: capacidade preditiva é marginal no agregado

Com alvo deslocado e split cronológico, o competidor relevante deixa de ser a
classe majoritária e passa a ser a **persistência** (prever que a melhor rota
em `t+H` é a de agora):

| H | modelo | persistência | ganho |
|---|---|---|---|
| 1 s | 0,7639 | 0,8263 | **−0,062** |
| 5 s | 0,7573 | 0,7470 | +0,010 |
| 15 s | 0,7538 | 0,7456 | +0,008 |
| 30 s | 0,7551 | 0,7401 | +0,015 |
| 60 s | 0,7595 | 0,7595 | 0,000 |

Em `H=1s` o modelo é **pior** que repetir a rota atual; nos demais horizontes
o ganho não passa de 1,5 ponto. No agregado, as features de banda/gargalo
**não antecipam** a troca de melhor rota.

### Resultado 3: o agregado esconde cenários opostos

Quebrando por regime de tráfego (`H=30s`):

| cenário | modelo | persistência | ganho |
|---|---|---|---|
| D1 (baseline) | 0,9919 | 0,9868 | +0,005 |
| D2 (tráfego constante) | 0,7395 | 0,6306 | **+0,109** |
| D3 (iperf longo) | 0,7572 | 0,6686 | **+0,089** |
| D4 (iperf concorrente) | 0,6273 | 0,6812 | **−0,054** |

Este é o achado central, e ele **contraria a expectativa intuitiva** de que o
sinal preditivo apareceria no cenário mais dinâmico:

- Há capacidade preditiva real sob tráfego **estruturado** (`D2`, `D3`): 9 a
  11 pontos acima da persistência. A degradação da banda é gradual e as
  features a capturam antes da troca de rota.
- Em `D4` (iperf concorrente) o modelo é **pior que não fazer nada**. A
  intermitência dos fluxos concorrentes é imprevisível neste horizonte, e o
  modelo treinado nos primeiros 80% extrapola mal.
- Em `D1` a persistência satura (98,7%) — a melhor rota praticamente não
  muda, e não há margem a disputar.

O ganho agregado de +0,015 é, portanto, a média de situações qualitativamente
opostas: `D4` cancela os ganhos de `D2`/`D3`. **Reportar apenas o número geral
seria enganoso** — é a razão pela qual toda análise deste notebook passou a
ser apresentada por cenário com o geral ao lado.

### Sobre a feature importance

No regime contemporâneo, a importância por permutação concentra-se nas
features de gargalo em janela (`gargalo_min_longa_30s`, `gargalo_min_curta_15s`)
mais que em `banda_media_Mbps` isolado, sugerindo que a *tendência recente*
do gargalo é mais discriminativa que seu valor pontual. MDI e permutação
divergem na posição intermediária, pelo viés conhecido do MDI a favor de
features de alta cardinalidade.

Dois padrões se repetem em ambos os regimes:

- **Em `D1`, a importância de praticamente todas as features é zero**, apesar
  da acurácia de 99%. Sem tráfego de fundo, diferenças estruturais entre
  rotas (não capturadas por nenhuma feature candidata) bastam para a árvore
  memorizar a resposta com poucos splits quase determinísticos.
- **No regime preditivo, `D4` tem as maiores importâncias da tabela**
  (`utilizacao_media_curta_15s` = 0,039; `gargalo_min_curta_15s` = 0,032) e
  ao mesmo tempo o pior ganho. O modelo depende fortemente dessas features,
  mas de uma forma que não generaliza para o período de teste — importância
  alta indica dependência, não acerto.

Sobre os valores **negativos** que aparecem em várias células: são esperados
e discutidos na Seção 11 ("Importâncias negativas").
"""),

md(r"""
## 11. Limitações

**Correção de unidade não aplicada aqui.** Diferente de `Feature_Store_Telemetria.ipynb`,
que reprocessa a partir de `banda_raw_rota_*.csv` cru, os datasets/D* já foram
gerados por uma versão anterior do protótipo; `banda.bwm` é a captura bruta do
`bwm-ng`, então a mesma correção de unidade (bytes/s → Mbps decimal, sem passar
por Mibit/s) se aplica igualmente aqui. As pequenas diferenças residuais frente
a `banda_rota_*.txt` (na ordem de poucos Mbps em cenários com tráfego
concorrente) refletem o mesmo efeito de arredondamento documentado no notebook
de referência, não um erro de reprocessamento.

**Volume por dataset.** Cada conjunto cobre uma execução de aproximadamente uma
hora (3600–3850 s úteis por rota), muito maior que a coleta de referência (30 s),
mas ainda uma única execução por cenário — não há repetições que permitam
estimar variância entre execuções do mesmo cenário.

**Vazamento no alvo.** A coluna `melhor_rota` permanece função determinística
da latência em todos os datasets, pela mesma razão descrita no notebook de
referência.

**Feature importance com vazamento controlado, mas não eliminado.** Mesmo
excluindo `latencia_*` e `bdp`, features de banda no mesmo instante (`gargalo_Mbps`,
`banda_media_Mbps`) ainda podem carregar parte da mesma causalidade que gera a
latência mais baixa (ex.: link congestionado eleva latência e reduz banda
simultaneamente), então a importância observada reflete correlação
contemporânea, não necessariamente uma relação causal ou preditiva
"antecedente".

**A análise das Seções 7–8 é contemporânea, não preditiva.** O formato largo
permite ao modelo comparar as 4 rotas no mesmo instante, mas essa comparação
usa métricas medidas *no momento presente*: ali o modelo não antecipa qual
rota será a melhor, e sim classifica, a posteriori, qual já era a melhor
naquele segundo. A **Seção 9** endereça essa limitação explicitamente, com
alvo deslocado (`y(t+H)`) e split temporal — seus resultados são a medida
honesta de capacidade preditiva; os da Seção 8, um limite superior otimista.

**A acurácia das Seções 7–8 é inflada pelo `shuffle=True`.** O split
aleatório sorteia instantes individualmente, colocando segundos consecutivos
— quase idênticos, dada a autocorrelação da série — simultaneamente em
treino e teste. O conjunto de teste passa a conter quase-duplicatas do
treino, e a acurácia mede em parte memorização, não generalização. A Seção 9
quantifica esse efeito mantendo a mesma tarefa (`H=0`) e trocando apenas o
protocolo de avaliação. Os números das seções anteriores foram preservados
para permitir essa comparação, mas não devem ser citados isoladamente como
desempenho do modelo.

**Importâncias negativas são esperadas, e informativas.** Em várias tabelas
aparecem valores negativos de importância por permutação (ex.:
`gargalo_min_curta_15s` = −0,0068 em D2 no regime preditivo). Isso **não é
erro de cálculo**: a importância por permutação é definida como
`acurácia_original − acurácia_com_a_coluna_embaralhada`, e nada impede que
essa diferença seja negativa — significa apenas que o modelo ficou *melhor*
ao ter aquela coluna destruída.

Há duas causas distintas, com leituras diferentes:

1. **Ruído amostral em torno de zero.** Quando a importância verdadeira é
   nula, a diferença medida oscila aleatoriamente e cai em negativo metade das
   vezes. É o caso dos valores minúsculos de `D1` (−0,0003, −0,0007), onde
   praticamente toda a coluna é zero: com `n_repeats=5` e poucos milhares de
   linhas de teste, a incerteza é da mesma ordem do efeito. **Leitura
   correta: a feature é irrelevante, não prejudicial.**
2. **A feature atrapalha de fato no conjunto de teste.** Quando a magnitude é
   grande demais para ser ruído (como os −0,009 de `D3` preditivo), o modelo
   aprendeu no treino uma relação que não se sustenta no período de teste, e
   embaralhar a coluna remove uma fonte ativa de erro. É sintoma de
   sobreajuste àquela feature — e aparece justamente onde o split temporal
   expõe mudança de regime entre os dois blocos.

Note que os negativos são muito mais frequentes nas tabelas **preditivas**
que nas contemporâneas. Isso é coerente: no regime contemporâneo o teste é
estatisticamente parecido com o treino, enquanto no preditivo, com split
cronológico, o teste é um trecho posterior da série, em que as relações
aprendidas podem ter deixado de valer.

Duas ressalvas de método, portanto: (a) valores negativos pequenos não devem
ser interpretados como "a feature prejudica", apenas como ausência de sinal;
(b) o `n_repeats` usado (5 por cenário, 10 no geral) é baixo para estimar
intervalos de confiança — as tabelas mostram médias sem desvio-padrão, e um
ranking entre features de importância próxima não é estatisticamente
distinguível. Para uso na dissertação, convém elevar `n_repeats` e reportar
a dispersão (`importances_std`).
"""),
]


def main():
    for indice, celula in enumerate(CELULAS):
        celula['id'] = f'celula-{indice:02d}'

    notebook = {
        'cells': CELULAS,
        'metadata': {
            'kernelspec': {
                'display_name': 'Python 3',
                'language': 'python',
                'name': 'python3',
            },
            'language_info': {'name': 'python'},
        },
        'nbformat': 4,
        'nbformat_minor': 5,
    }
    with open(DESTINO, 'w') as arquivo:
        json.dump(notebook, arquivo, indent=1, ensure_ascii=False)
        arquivo.write('\n')
    print(f'{DESTINO}: {len(CELULAS)} celulas')


if __name__ == '__main__':
    main()
