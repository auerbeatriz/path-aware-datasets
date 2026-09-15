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
mesmos dois layouts do notebook de referência (longo em `csv/`, largo
compatível com `datasets/D*` em `csv_ml/`). As tabelas em memória de todos os
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

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

import pipeline as fs

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
    arquivos = sorted(glob.glob(f'{pasta}/csv/*.csv') + glob.glob(f'{pasta}/csv_ml/*'))
    total_bytes = sum(os.path.getsize(a) for a in arquivos)
    print(f"{dataset}: {len(arquivos)} arquivos, {total_bytes:,} bytes em {pasta}/")
"""),

md(r"""
## 4.1 Arquivos de output e significado das features

### Arquivos gerados por dataset

Para cada `feature_store/data/<DATASET>/`, o pipeline grava dois layouts:

**Layout longo** (`csv/`) — um arquivo por feature group, grão explícito na chave:

| arquivo | grão | conteúdo |
|---|---|---|
| `fg_latencia.csv` | (run, rota, ts) | RTT medido por ping |
| `fg_banda_interface.csv` | (run, rota, interface, ts) | taxa e utilização por interface |
| `fg_banda_rota.csv` | (run, rota, ts) | gargalo e agregados do caminho |
| `consolidado.csv` | (run, rota, ts) | junção, features de janela, deltas e alvo — a tabela principal |
| `dim_rota.csv` | (rota) | atributos fixos do caminho (dimensão) |

**Layout largo** (`csv_ml/`) — compatível com `datasets/D*`, uma coluna por rota:

| arquivo | conteúdo |
|---|---|
| `latencia_rotas_h1_h6.csv` | latência (ms) de cada rota, uma coluna por rota, indexado por `timestamp` |
| `banda_rotas_h1_h6.csv` | gargalo (Mbps) de cada rota, mesmo layout |
| `rotulos_h1_h6.txt` | índice (base 1) da rota de menor latência em cada instante |

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
## 8. Análise de feature importance

Reaproveita o ferramental de `Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb`
(RandomForest + `sklearn`) para estimar a importância relativa de cada feature
da store na previsão de `melhor_rota`, combinando os dois métodos usuais:

- **Importância por impureza (MDI)**: `feature_importances_` do RandomForest,
  calculada durante o treino a partir da redução média de impureza (Gini) em
  cada split. É rápida, mas enviesada a favor de features com muitos valores
  distintos e não reflete diretamente o desempenho do modelo.
- **Importância por permutação**: embaralha cada coluna (uma de cada vez) no
  conjunto de teste e mede a queda de acurácia. É mais confiável — reflete o
  impacto real na métrica escolhida — mas mais cara computacionalmente.

Como `melhor_rota` é função determinística de `latencia_ms` (ver seção de
Limitações), as colunas derivadas de latência dominam a análise por
construção. A célula de preparação dos dados por isso oferece a opção de
excluir o grupo `latencia_*` para revelar a importância relativa **dentro**
das features de banda/gargalo — a pergunta mais interessante do ponto de
vista de um modelo que não tenha acesso direto à latência da rota candidata.

Além da análise geral (todos os datasets combinados), a seção também repete o
cálculo **separadamente por cenário de tráfego** (`D1`/`D1b`, `D2`/`D2b`,
`D3`/`D3b`, `D4`/`D4b`), permitindo verificar se a importância relativa das
features muda conforme o regime de congestionamento de fundo.
"""),

code(r"""
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.inspection import permutation_importance

RANDOM_STATE = 1234
"""),

md(r"""
### Preparação dos dados

Usa o conjunto consolidado de todos os datasets (`completo`, seção 7), com
`melhor_rota` como alvo. Colunas identificadoras/temporais e as próprias
colunas de origem do alvo (que definiriam `melhor_rota` por construção, se
mantidas por rota) são descartadas; linhas sem alvo (`melhor_rota` nulo, por
falha de ping em alguma rota naquele instante) são removidas.

`EXCLUIR_LATENCIA` controla se as features de latência entram na análise —
mantenha `True` para focar na importância relativa das features de banda.
"""),

code(r"""
EXCLUIR_LATENCIA = True

COLUNAS_NAO_FEATURE = {
    'dataset_id', 'run_id', 'rota_id', 'ts_epoch', 'datetime_utc',
    'tempo_relativo_s', 'melhor_rota',
}

base = completo.dropna(subset=['melhor_rota']).copy()

candidatas = [c for c in base.columns if c not in COLUNAS_NAO_FEATURE]
if EXCLUIR_LATENCIA:
    candidatas = [c for c in candidatas if not c.startswith('latencia_')
                  and c not in ('bdp',)]

# Descarta colunas totalmente nulas para o corte atual (ex.: features de janela
# sem amostras suficientes no início de cada run)
candidatas = [c for c in candidatas if base[c].notna().any()]

X_fi = base[candidatas].fillna(base[candidatas].median(numeric_only=True))
y_fi = base['melhor_rota'].astype(int)

print(f"features candidatas: {len(candidatas)}")
print(f"registros: {len(X_fi)}")
print(f"classes (rotas): {sorted(y_fi.unique())}")
"""),

md(r"""
### Treino do RandomForest

Split treino/teste estratificado (80/20), igual ao usado no notebook de
referência, para permitir tanto a importância por impureza (calculada no
treino) quanto a importância por permutação (calculada no teste, para não
inflar a métrica com overfitting).
"""),

code(r"""
X_train_fi, X_test_fi, y_train_fi, y_test_fi = train_test_split(
    X_fi, y_fi, test_size=0.2, random_state=RANDOM_STATE, stratify=y_fi
)

modelo_fi = RandomForestClassifier(n_estimators=300, random_state=RANDOM_STATE, n_jobs=-1)
modelo_fi.fit(X_train_fi, y_train_fi)

acuracia_fi = modelo_fi.score(X_test_fi, y_test_fi)
print(f"acurácia no teste: {acuracia_fi:.4f}")
"""),

md(r"""
### Importância por impureza (MDI)
"""),

code(r"""
importancia_mdi = pd.Series(modelo_fi.feature_importances_, index=candidatas)
importancia_mdi = importancia_mdi.sort_values(ascending=False)

top_n = min(20, len(importancia_mdi))
fig, ax = plt.subplots(figsize=(9, 0.35 * top_n + 1))
importancia_mdi.head(top_n).iloc[::-1].plot.barh(ax=ax, color='steelblue')
ax.set_xlabel('Importância (redução média de impureza)')
ax.set_title(f'Top {top_n} features — MDI (RandomForest)')
ax.grid(axis='x', alpha=0.3)
plt.tight_layout()
plt.show()

importancia_mdi.head(top_n)
"""),

md(r"""
### Importância por permutação

Calculada sobre o conjunto de teste, com 10 repetições por feature para
estimar a variabilidade (barras de erro = desvio padrão entre repetições).
"""),

code(r"""
resultado_perm = permutation_importance(
    modelo_fi, X_test_fi, y_test_fi,
    n_repeats=10, random_state=RANDOM_STATE, n_jobs=1
)

importancia_perm = pd.Series(resultado_perm.importances_mean, index=candidatas)
desvio_perm = pd.Series(resultado_perm.importances_std, index=candidatas)
ordem_perm = importancia_perm.sort_values(ascending=False)

top_n = min(20, len(ordem_perm))
fig, ax = plt.subplots(figsize=(9, 0.35 * top_n + 1))
ax.barh(
    ordem_perm.head(top_n).index[::-1],
    ordem_perm.head(top_n).iloc[::-1],
    xerr=desvio_perm.reindex(ordem_perm.head(top_n).index).iloc[::-1],
    color='darkorange',
)
ax.set_xlabel('Queda de acurácia ao permutar (média ± desvio)')
ax.set_title(f'Top {top_n} features — Importância por permutação')
ax.grid(axis='x', alpha=0.3)
plt.tight_layout()
plt.show()

ordem_perm.head(top_n)
"""),

md(r"""
### Comparação entre os dois métodos

Concorda quando a mesma feature aparece bem posicionada nos dois rankings;
diverge tipicamente para features de alta cardinalidade, que a MDI tende a
supervalorizar frente ao real impacto na acurácia.
"""),

code(r"""
comparacao_fi = pd.DataFrame({
    'mdi': importancia_mdi,
    'permutacao': importancia_perm,
}).sort_values('permutacao', ascending=False)

comparacao_fi['rank_mdi'] = comparacao_fi['mdi'].rank(ascending=False).astype(int)
comparacao_fi['rank_permutacao'] = comparacao_fi['permutacao'].rank(ascending=False).astype(int)

comparacao_fi.head(15)
"""),

md(r"""
### Feature importance por cenário

A análise anterior combina todos os datasets — mas cada par (`D1`/`D1b`,
`D2`/`D2b`, `D3`/`D3b`, `D4`/`D4b`) representa um cenário de tráfego de fundo
distinto (ver Seção "Conjuntos processados"), e a importância relativa das
features pode variar conforme o regime de congestionamento. Esta seção repete
o treino e a importância por permutação **separadamente para cada cenário**,
usando o mesmo conjunto de 13 features de banda/gargalo (sem latência), para
permitir comparar se, por exemplo, o gargalo importa mais sob tráfego
concorrente (`D4`) do que na linha de base (`D1`).
"""),

code(r"""
CENARIOS = {
    'D1 (baseline)': ['D1', 'D1b'],
    'D2 (tráfego constante)': ['D2', 'D2b'],
    'D3 (iperf longo)': ['D3', 'D3b'],
    'D4 (iperf concorrente)': ['D4', 'D4b'],
}

importancias_por_cenario = {}
importancias_mdi_por_cenario = {}
acuracias_por_cenario = {}

for nome_cenario, datasets_cenario in CENARIOS.items():
    base_c = base[base.dataset_id.isin(datasets_cenario)]
    X_c = base_c[candidatas]
    y_c = base_c['melhor_rota'].astype(int)

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

    importancias_por_cenario[nome_cenario] = pd.Series(
        resultado_perm_c.importances_mean, index=candidatas
    )
    importancias_mdi_por_cenario[nome_cenario] = pd.Series(
        modelo_c.feature_importances_, index=candidatas
    )
    acuracias_por_cenario[nome_cenario] = acuracia_c

    print(f"{nome_cenario:26s} | registros: {len(X_c):6d} | acurácia: {acuracia_c:.4f}")
"""),

md(r"""
### Comparação entre cenários e resultado geral

Tabela com a importância por permutação de cada feature em cada cenário,
lado a lado com a importância geral (todos os datasets combinados, calculada
anteriormente), ordenada pela importância geral. Isso evidencia tanto
features consistentemente importantes em todos os cenários quanto features
cuja relevância é específica de um regime de tráfego.
"""),

code(r"""
comparacao_cenarios = pd.DataFrame(importancias_por_cenario)
comparacao_cenarios['geral (todos os datasets)'] = importancia_perm
comparacao_cenarios = comparacao_cenarios.sort_values('geral (todos os datasets)', ascending=False)

comparacao_cenarios
"""),

code(r"""
fig, ax = plt.subplots(figsize=(11, 6))
comparacao_cenarios.plot.barh(ax=ax, width=0.8)
ax.set_xlabel('Importância por permutação (queda de acurácia)')
ax.set_title('Importância por permutação — por cenário vs. geral')
ax.invert_yaxis()
ax.grid(axis='x', alpha=0.3)
ax.legend(fontsize=8, loc='lower right')
plt.tight_layout()
plt.show()
"""),

md(r"""
### MDI por cenário e resultado geral

Mesma comparação anterior, agora usando a importância por impureza (MDI)
em vez de permutação — permite ver se a divergência entre os dois métodos
observada no resultado geral (Seção 8) também aparece dentro de cada
cenário individualmente.
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
ax.set_title('Importância por MDI — por cenário vs. geral')
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
difícil quando restrita a um único regime de tráfego (menos variação nos
dados, porém menos exemplos de treino).
"""),

code(r"""
resumo_acuracia = pd.Series(acuracias_por_cenario)
resumo_acuracia['geral (todos os datasets)'] = acuracia_fi
resumo_acuracia.to_frame('acurácia no teste')
"""),

md(r"""
### Análise complementar incluindo latência

As análises anteriores excluem `latencia_*` e `bdp` deliberadamente, para
evitar o vazamento trivial descrito na Seção 11. Esta subseção repete o
treino **incluindo** essas features, tanto no conjunto geral (todos os
datasets) quanto **separadamente por cenário** (mesmos pares `D1`/`D1b` a
`D4`/`D4b` usados na análise sem latência), para quantificar diretamente o
quanto elas dominam quando presentes, se essa dominância é uniforme entre
cenários, e para confirmar que o exercício de exclusão não é apenas uma
precaução teórica.
"""),

code(r"""
candidatas_com_latencia = [c for c in base.columns if c not in COLUNAS_NAO_FEATURE]
candidatas_com_latencia = [c for c in candidatas_com_latencia if base[c].notna().any()]

X_cl = base[candidatas_com_latencia].fillna(base[candidatas_com_latencia].median(numeric_only=True))
y_cl = base['melhor_rota'].astype(int)

X_train_cl, X_test_cl, y_train_cl, y_test_cl = train_test_split(
    X_cl, y_cl, test_size=0.2, random_state=RANDOM_STATE, stratify=y_cl
)

modelo_cl = RandomForestClassifier(n_estimators=300, random_state=RANDOM_STATE, n_jobs=-1)
modelo_cl.fit(X_train_cl, y_train_cl)

acuracia_cl = modelo_cl.score(X_test_cl, y_test_cl)
print(f"features (com latência): {len(candidatas_com_latencia)}")
print(f"acurácia no teste (geral): {acuracia_cl:.4f}")

# Repete o treino separadamente por cenário, com o mesmo conjunto de features
# (com latência), para verificar se a dominância da latência é uniforme entre
# regimes de tráfego de fundo.
importancias_por_cenario_cl = {}
importancias_mdi_por_cenario_cl = {}
acuracias_por_cenario_cl = {}

print()
for nome_cenario, datasets_cenario in CENARIOS.items():
    base_c = base[base.dataset_id.isin(datasets_cenario)]
    X_c_cl = base_c[candidatas_com_latencia].fillna(
        base_c[candidatas_com_latencia].median(numeric_only=True)
    )
    y_c_cl = base_c['melhor_rota'].astype(int)

    X_train_c_cl, X_test_c_cl, y_train_c_cl, y_test_c_cl = train_test_split(
        X_c_cl, y_c_cl, test_size=0.2, random_state=RANDOM_STATE, stratify=y_c_cl
    )

    modelo_c_cl = RandomForestClassifier(n_estimators=200, random_state=RANDOM_STATE, n_jobs=-1)
    modelo_c_cl.fit(X_train_c_cl, y_train_c_cl)
    acuracia_c_cl = modelo_c_cl.score(X_test_c_cl, y_test_c_cl)

    resultado_perm_c_cl = permutation_importance(
        modelo_c_cl, X_test_c_cl, y_test_c_cl,
        n_repeats=5, random_state=RANDOM_STATE, n_jobs=1
    )

    importancias_por_cenario_cl[nome_cenario] = pd.Series(
        resultado_perm_c_cl.importances_mean, index=candidatas_com_latencia
    )
    importancias_mdi_por_cenario_cl[nome_cenario] = pd.Series(
        modelo_c_cl.feature_importances_, index=candidatas_com_latencia
    )
    acuracias_por_cenario_cl[nome_cenario] = acuracia_c_cl

    print(f"{nome_cenario:26s} | registros: {len(X_c_cl):6d} | acurácia: {acuracia_c_cl:.4f}")
"""),

code(r"""
resultado_perm_cl = permutation_importance(
    modelo_cl, X_test_cl, y_test_cl,
    n_repeats=10, random_state=RANDOM_STATE, n_jobs=1
)

importancia_perm_cl = pd.Series(resultado_perm_cl.importances_mean, index=candidatas_com_latencia)
desvio_perm_cl = pd.Series(resultado_perm_cl.importances_std, index=candidatas_com_latencia)
ordem_perm_cl = importancia_perm_cl.sort_values(ascending=False)

top_n = min(20, len(ordem_perm_cl))
fig, ax = plt.subplots(figsize=(9, 0.35 * top_n + 1))
cores = ['crimson' if c.startswith('latencia_') or c == 'bdp' else 'steelblue'
         for c in ordem_perm_cl.head(top_n).index[::-1]]
ax.barh(
    ordem_perm_cl.head(top_n).index[::-1],
    ordem_perm_cl.head(top_n).iloc[::-1],
    xerr=desvio_perm_cl.reindex(ordem_perm_cl.head(top_n).index).iloc[::-1],
    color=cores,
)
ax.set_xlabel('Queda de acurácia ao permutar (média ± desvio)')
ax.set_title(f'Top {top_n} features — Importância por permutação (com latência, geral)')
ax.grid(axis='x', alpha=0.3)
plt.tight_layout()
plt.show()

print("vermelho = feature de latência/bdp | azul = feature de banda/gargalo")
ordem_perm_cl.head(top_n)
"""),

md(r"""
### Comparação entre cenários e resultado geral (com latência)

Mesmo formato da comparação por cenário sem latência, agora com o conjunto
de 25 features (banda/gargalo + latência/bdp), lado a lado com o resultado
geral.
"""),

code(r"""
comparacao_cenarios_cl = pd.DataFrame(importancias_por_cenario_cl)
comparacao_cenarios_cl['geral (todos os datasets)'] = importancia_perm_cl
comparacao_cenarios_cl = comparacao_cenarios_cl.sort_values('geral (todos os datasets)', ascending=False)

comparacao_cenarios_cl
"""),

code(r"""
fig, ax = plt.subplots(figsize=(11, 7))
comparacao_cenarios_cl.plot.barh(ax=ax, width=0.8)
ax.set_xlabel('Importância por permutação (queda de acurácia)')
ax.set_title('Importância por permutação (com latência) — por cenário vs. geral')
ax.invert_yaxis()
ax.grid(axis='x', alpha=0.3)
ax.legend(fontsize=8, loc='lower right')
plt.tight_layout()
plt.show()
"""),

md(r"""
### MDI por cenário e resultado geral (com latência)

Mesma comparação de MDI por cenário feita na análise sem latência, agora com
o conjunto de 25 features. Espera-se que `latencia_ms` e demais features de
latência dominem o MDI em todos os cenários, dado o vazamento de rótulo.
"""),

code(r"""
importancia_mdi_cl = pd.Series(modelo_cl.feature_importances_, index=candidatas_com_latencia)

comparacao_cenarios_mdi_cl = pd.DataFrame(importancias_mdi_por_cenario_cl)
comparacao_cenarios_mdi_cl['geral (todos os datasets)'] = importancia_mdi_cl
comparacao_cenarios_mdi_cl = comparacao_cenarios_mdi_cl.sort_values('geral (todos os datasets)', ascending=False)

comparacao_cenarios_mdi_cl
"""),

code(r"""
fig, ax = plt.subplots(figsize=(11, 7))
comparacao_cenarios_mdi_cl.plot.barh(ax=ax, width=0.8)
ax.set_xlabel('Importância por MDI (redução média de impureza)')
ax.set_title('Importância por MDI (com latência) — por cenário vs. geral')
ax.invert_yaxis()
ax.grid(axis='x', alpha=0.3)
ax.legend(fontsize=8, loc='lower right')
plt.tight_layout()
plt.show()
"""),

md(r"""
### Acurácia por cenário (com latência)

Mesma comparação feita sem latência, agora com as features de latência/bdp
incluídas — permite ver, cenário a cenário, o ganho de acurácia trazido pela
latência frente ao modelo apenas com banda/gargalo.
"""),

code(r"""
resumo_acuracia_cl = pd.Series(acuracias_por_cenario_cl)
resumo_acuracia_cl['geral (todos os datasets)'] = acuracia_cl

comparacao_acuracia = pd.DataFrame({
    'sem latência': resumo_acuracia,
    'com latência': resumo_acuracia_cl,
})
comparacao_acuracia['ganho'] = comparacao_acuracia['com latência'] - comparacao_acuracia['sem latência']
comparacao_acuracia
"""),

md(r"""
### Onde as features de banda ficam no ranking combinado

Isola, dentro do ranking completo (com latência), a posição das features de
banda/gargalo — mostrando quanto do espaço de importância elas ainda ocupam
mesmo competindo diretamente com a latência.
"""),

code(r"""
ranking_completo = ordem_perm_cl.rank(ascending=False).astype(int)
posicoes_banda = ranking_completo[[c for c in candidatas_com_latencia
                                    if not c.startswith('latencia_') and c != 'bdp']]

print(f"acurácia sem latência : {acuracia_fi:.4f}  ({len(candidatas)} features)")
print(f"acurácia com latência : {acuracia_cl:.4f}  ({len(candidatas_com_latencia)} features)")
print(f"ganho de acurácia      : {acuracia_cl - acuracia_fi:+.4f}")
print()
print("posição das features de banda no ranking combinado (1 = mais importante):")
posicoes_banda.sort_values().to_frame('posição no ranking')
"""),

md(r"""
## 10. Resumo e conclusões

### O que foi feito

A análise partiu do conjunto consolidado de todos os 8 datasets elegíveis
(`completo`, Seção 7 — 117.718 registros, 4 rotas por dataset), com
`melhor_rota` como alvo. Um `RandomForestClassifier` (300 árvores) foi
treinado em split estratificado 80/20, e a importância de cada feature foi
medida por dois métodos complementares: **MDI** (redução de impureza,
calculada no treino) e **importância por permutação** (queda de acurácia ao
embaralhar cada coluna no teste, 10 repetições). A análise foi repetida
também separadamente por cenário de tráfego (`D1`/`D1b` a `D4`/`D4b`), tanto
excluindo quanto incluindo as features de latência.

### Features eliminadas e motivo

| feature(s) removida(s) | motivo da exclusão |
|---|---|
| `latencia_*` (p95, jitter, média em todas as janelas) e `latencia_ms` | Definem `melhor_rota` por construção (`melhor_rota = argmin(latencia_ms)`), então dominariam a importância trivialmente sem agregar informação — ver "Vazamento no alvo" na Seção 11. |
| `bdp` | Calculado como `gargalo_Mbps × latencia_ms`, herda o mesmo vazamento por incorporar `latencia_ms` diretamente na fórmula. |
| `dataset_id`, `run_id`, `rota_id`, `ts_epoch`, `datetime_utc`, `tempo_relativo_s` | Identificadores e marcações temporais/de execução, não sinais de rede — mantê-los correlacionaria o modelo a artefatos da coleta (ex.: qual dataset ou run gerou a linha) em vez do comportamento da rede. |
| Colunas de janela integralmente nulas no corte atual | Removidas dinamicamente (`base[c].notna().any()`) — nenhuma das 13 features de banda restantes caiu nessa condição no conjunto completo, mas o filtro protege reexecuções com subconjuntos menores de dados. |

Restaram **13 features**, todas derivadas de banda/gargalo/utilização nas
métricas instantâneas e nas três janelas (`micro`=5s, `curta`=15s,
`longa`=30s).

### Conclusão e interpretação dos resultados

- **Acurácia de 84,6%** prevendo a rota de menor latência **sem usar
  qualquer feature de latência**, apenas com sinais de banda/gargalo — indício
  de que o gargalo de banda por si só carrega bastante informação sobre qual
  caminho está mais congestionado, embora não seja perfeitamente equivalente à
  latência (daí a diferença dos 100% obtidos ao incluir `latencia_ms`).
- **`banda_media_Mbps` domina os dois rankings** (1º lugar em MDI e em
  permutação, com folga): a banda média entre as interfaces do caminho é o
  sinal instantâneo mais informativo, mais até que o próprio gargalo mínimo.
- **MDI e permutação divergem na posição intermediária**: MDI privilegia
  `gargalo_Mbps` e `util_max_pct` (2º-3º lugar), enquanto a permutação
  privilegia as versões em janela do gargalo (`gargalo_min_longa/curta/micro`,
  2º-4º lugar). Isso é consistente com o viés conhecido do MDI a favor de
  features de alta cardinalidade/variância (as métricas instantâneas têm mais
  valores distintos que os agregados de janela) — a permutação, medindo o
  impacto real na acurácia, é a referência mais confiável aqui.
- **Contexto temporal importa mais que o instante isolado para o gargalo**:
  as três variantes de `gargalo_min_{janela}` aparecem entre as 4 mais
  importantes por permutação, sugerindo que a *tendência recente* do gargalo
  (não apenas seu valor pontual) ajuda o modelo a diferenciar rotas.
- **A importância varia por cenário de tráfego**: repetindo a análise
  separadamente por par de datasets (`D1`/`D1b` a `D4`/`D4b`), o padrão muda
  substancialmente entre cenários. Em `D1` (baseline, sem tráfego de fundo) a
  acurácia é de 99,4% mas as importâncias por permutação são praticamente
  nulas para todas as features — a banda quase não varia nesse cenário
  (valores próximos de 100 Mbps o tempo todo), então o RandomForest explora
  diferenças residuais mínimas e consistentes entre rotas, não um sinal de
  congestionamento real. Já em `D2` (tráfego constante), `banda_media_Mbps`
  concentra a maior parte da importância (0,16, muito acima da média geral de
  0,07); em `D3`/`D4` (fluxos iperf), a importância se distribui mais entre
  `gargalo_min_{janela}`, coerente com a natureza intermitente desses
  cenários. Isso confirma que a importância "geral" (todos os datasets
  combinados) é uma média que mistura regimes bem diferentes.
- **Interpretação com cautela**: como discutido na próxima seção, a
  correlação contemporânea entre banda e latência (ambas reagem ao mesmo
  congestionamento) significa que esta importância reflete associação, não
  necessariamente uma relação preditiva utilizável antes do fato consumado.
- **Incluir latência eleva a acurácia geral para 89,0%** (25 features, ante
  84,6% com 13 features de banda apenas) — um ganho de 4,5 pontos percentuais,
  não os 100% que uma dependência determinística perfeita sugeriria à
  primeira vista. `latencia_ms` domina isoladamente a importância por
  permutação nesse cenário combinado (0,062, cerca de 3× a segunda posição),
  mas `banda_media_Mbps`, `gargalo_Mbps` e `util_max_pct` continuam entre as
  10 mais importantes por MDI mesmo competindo diretamente com toda a família
  de features de latência — evidência adicional de que carregam sinal
  complementar, não apenas redundante.
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
