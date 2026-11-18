"""Gera o Feature_Store_Telemetria.ipynb a partir das celulas definidas aqui.

Manter o notebook sob um gerador evita conflitos de merge no JSON e garante que
a narrativa acompanhe pipeline.py. Executar com:

    .venv/bin/python feature_store/construir_notebook.py

O texto das celulas markdown segue registro impessoal, adequado a publicacao.
"""

import json

DESTINO = 'Feature_Store_Telemetria.ipynb'


def md(texto):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': texto.strip().splitlines(keepends=True)}


def code(texto):
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {},
            'outputs': [], 'source': texto.strip().splitlines(keepends=True)}


CELULAS = [
md(r"""
# Feature Store de Telemetria de Rede

Este notebook documenta a construção de uma *feature store* a partir da
telemetria gerada pelo protótipo Mininet, disponível em `prototipo/relatorios/`.

O cenário experimental compreende **quatro caminhos concorrentes** entre os
switches `s1` e `s6`. Cada caminho dispõe de um par de hosts dedicado à medição
de latência, de modo que as rotas sejam observadas de forma independente. O
tráfego de carga consiste em um fluxo iperf UDP de 20 Mbps entre `h10` e `h60`.

## Modelo de dados

A store organiza-se em *feature groups* independentes, cada um definido em seu
próprio grão e compartilhando a chave de entidade canônica
`(run_id, rota_id, ts_epoch)`:

| feature group | grão | conteúdo |
|---|---|---|
| `fg_latencia` | (run, rota, ts) | RTT medido por ping |
| `fg_banda_interface` | (run, rota, interface, ts) | taxa e utilização por interface |
| `fg_banda_rota` | (run, rota, ts) | gargalo e agregados do caminho |
| `consolidado` | (run, rota, ts) | junção, features de janela e alvo |
| `dim_rota` | (rota) | atributos fixos do caminho (dimensão) |

Latência e banda não requerem coabitação em uma única tabela; a chave comum é
condição suficiente para a junção. Esta é realizada sob demanda pela função
`get_features`, e a tabela consolidada constitui o artefato derivado consumido
pelo notebook de aprendizado de máquina.

## Organização

 1. Importação
 2. Alinhamento temporal entre os dois relógios
 3. Topologia: capacidade das interfaces e dimensão das rotas
 4. Ingestão da banda
 5. Ingestão da latência
 6. Agregação da banda no grão da rota
 7. Consolidação e features de janela deslizante
 8. Persistência em CSV
 9. Descrição da feature store construída
10. Verificação
11. Visualização de validação
12. Consulta à store
13. Limitações desta coleta
"""),

md(r"""
## 1. Importação

A lógica de processamento reside em `feature_store/pipeline.py`, o que permite
sua verificação por asserções. Este notebook cumpre as funções de documentação
e validação visual.

A célula seguinte localiza a raiz do projeto a partir do diretório de trabalho
corrente e redefine o diretório ativo. O procedimento é necessário porque os
caminhos relativos empregados (`prototipo/relatorios`, `datasets/D*`) dependem
do diretório de inicialização do kernel, que difere entre `jupyter nbconvert`,
Jupyter Lab e a extensão Jupyter do VSCode — nesta última, o padrão é
`${fileDirname}`.
"""),

code(r"""
import os
import sys
from pathlib import Path


def raiz_do_projeto(marcadores=('prototipo', 'feature_store')):
    # Percorre o cwd e seus ancestrais até localizar os diretórios marcadores
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
## 2. Alinhamento temporal

O alinhamento entre as duas fontes é pré-condição para a consolidação, e sua
necessidade decorre de duas características dos dados de origem.

A primeira é a divergência de escala temporal. O protótipo registra a latência
por meio de `datetime.fromtimestamp(...).strftime(...)` (`relatorios.py:47`),
que produz hora local sem indicação de fuso e descarta o *epoch*. A banda, por
sua vez, provém do `bwm-ng` e preserva o *epoch* original. As duas séries
situam-se, portanto, em escalas distintas: uma junção direta por *timestamp*
resulta em zero registros contendo ambas as métricas.

A segunda é a presença de múltiplas execuções em um mesmo arquivo. O `bwm-ng`
abre o arquivo de saída em modo *append* (`telemetria.py:310`), de modo que
coletas sucessivas se acumulam. Os arquivos `banda_raw_*.csv` contêm duas
execuções, separadas por um intervalo sem amostras.

O arquivo `eventos.txt` permite resolver ambas as questões. Nele são registrados
os instantes BEGIN e END na mesma hora local da latência, ao passo que o
`bwm-ng` registra *epoch* — o arquivo constitui, assim, uma ponte entre as duas
escalas. Da comparação entre o evento BEGIN de banda e a primeira amostra de
cada execução candidata deriva-se o deslocamento, e a execução cujo resíduo é
mínimo é identificada como válida.

Cabe registrar que o alinhamento por *tempo relativo* — segundos decorridos
desde o início de cada fonte — não é adequado neste caso, pois associaria o
instante inicial da banda, pertencente à execução residual, ao instante inicial
da latência, deslocando as séries.
""") ,

code(r"""
alinhamento = fs.inferir_alinhamento()

print(f"deslocamento inferido : {alinhamento['offset_s']} s "
      f"({alinhamento['offset_s'] // 3600} h)")
print(f"resíduo               : {alinhamento['residuo_s']:.0f} s")
print(f"execução válida       : {alinhamento['run_id']}")
print(f"janela (epoch)        : {alinhamento['t_ini']} .. {alinhamento['t_fim']}")
print(f"janela (UTC)          : {pd.to_datetime(alinhamento['t_ini'], unit='s')} .. "
      f"{pd.to_datetime(alinhamento['t_fim'], unit='s')}")
print()
print("candidatos avaliados (resíduo em relação à hora inteira):")
for candidato in alinhamento['candidatos']:
    print(f"  execução {candidato['run_id']}: resíduo {candidato['residuo_s']:6.0f} s  "
          f"epoch {candidato['t_ini']}..{candidato['t_fim']}")
"""),

md(r"""
A execução descartada apresenta resíduo de 59 s, enquanto a execução válida
apresenta resíduo nulo. O deslocamento não é fixado no código: coletas
provenientes de máquinas com outro fuso são tratadas pelo mesmo cálculo. Caso a
premissa de diferença inteira de horas não se verifique, `inferir_alinhamento`
levanta exceção, em vez de produzir um alinhamento incorreto de forma
silenciosa.
"""),

md(r"""
## 3. Topologia

Desta etapa resultam a capacidade de cada interface, o atraso configurado por
enlace e o caminho percorrido por cada rota.

A numeração das interfaces reproduz a ordem dos `addLink` em `topologia.py`, que
corresponde à ordem dos enlaces em `config.json`. O método
`topologia.get_interfaces_links()` resolve essa correspondência de forma mais
robusta, por meio de `Topo.port()`, porém requer uma instância ativa de `Topo` e
não se aplica à leitura dos relatórios fora da execução do protótipo.
"""),

code(r"""
topologia = fs.carregar_topologia()

print("capacidade por interface (Mbps), enlaces inter-switch:")
for interface, capacidade in sorted(topologia['capacidade_por_interface'].items()):
    if capacidade == 100.0:
        print(f"  {interface}: {capacidade}")

print()
dim_rota = fs.metadados_das_rotas(topologia)
dim_rota
"""),

md(r"""
### Distinção entre dimensão e features

O atributo `atraso_cfg_ms` corresponde ao RTT teórico do caminho, obtido como
duas vezes a soma dos atrasos configurados nos enlaces, e `n_links_sw` indica a
quantidade de enlaces inter-switch. Ambos são úteis à interpretação dos
resultados: a rota `h14_h64`, por exemplo, é a mais longa em número de saltos
(cinco enlaces) e, simultaneamente, a de menor atraso configurado (18 ms), o que
evidencia que extensão e atraso não são equivalentes nesta topologia.

Tais atributos, entretanto, **não constituem features da série temporal**. Como
a topologia permanece inalterada ao longo de uma coleta, essas colunas
apresentam variância nula dentro de cada rota e são função determinística de
`rota_id`. Incorporadas à matriz de treinamento, atuariam como identificadores
da rota, permitindo ao modelo distingui-las sem inferir qualquer informação
sobre o estado da rede.

Pelo mesmo motivo, duas features derivadas foram excluídas do conjunto:
`latencia_por_salto` (`latencia / n_links_sw`) e `folga_vs_atraso_cfg`
(`latencia - atraso_cfg_ms`). Por consistirem na latência escalada ou deslocada
por uma constante da rota, sua correlação com `latencia_ms` dentro de cada rota
é exatamente `1.0`, conforme se verifica a seguir.

A store separa, portanto, a **dimensão** (`dim_rota.csv`, atributos fixos) dos
**fatos** (os feature groups, séries temporais). A recuperação conjunta, quando
o objetivo for a comparação entre rotas, faz-se por
`get_features(incluir_dim_rota=True)`.
"""),

code(r"""
# Verificação da redundância das normalizações pela topologia
amostra = fs.get_features(incluir_dim_rota=True)
amostra = amostra[amostra.latencia_ms.notna()].copy()
amostra['latencia_por_salto'] = amostra.latencia_ms / amostra.n_links_sw
amostra['folga_vs_atraso_cfg'] = amostra.latencia_ms - amostra.atraso_cfg_ms

print("correlação com latencia_ms, dentro de cada rota:")
for derivada in ['latencia_por_salto', 'folga_vs_atraso_cfg']:
    correlacoes = amostra.groupby('rota_id').apply(
        lambda g: g[derivada].corr(g.latencia_ms), include_groups=False)
    print(f"  {derivada:22s} {correlacoes.round(6).to_dict()}")
"""),

md(r"""
## 4. Ingestão da banda

A ingestão parte dos arquivos `banda_raw_rota_*.csv`, saída não processada do
`bwm-ng`, e não dos `banda_tratada_*.csv`, por duas razões.

A primeira é a perda de uma amostra: `parser_banda.py:17` invoca `read_csv` sem
`header=None` e o `bwm-ng` não emite linha de cabeçalho, de modo que a primeira
linha de dados é interpretada como nome de coluna.

A segunda diz respeito às unidades: a função `toMbps` divide por `1 << 20`,
resultando em Mibit/s, grandeza subtraída de uma capacidade de 100 Mbit/s
decimal definida pelo TCLink. A conversão adotada nesta etapa emprega `1e6`,
coerente com o parâmetro `bw=100`.

A etapa descarta ainda a linha agregada `total` e restringe os dados à janela da
execução válida.
"""),

code(r"""
fg_banda_interface = fs.ingerir_banda(alinhamento, topologia)

print(f"dimensões: {fg_banda_interface.shape}")
print("interfaces por rota:")
for rota, grupo in fg_banda_interface.groupby('rota_id'):
    print(f"  {rota}: {sorted(grupo.interface.unique())}")

fg_banda_interface.head()
"""),

md(r"""
As interfaces repetem-se entre rotas: `s1-eth1` integra duas delas, `s2-eth2`
igualmente, e assim sucessivamente. Essa sobreposição caracteriza o cenário como
*path-aware*, uma vez que o tráfego em um caminho afeta os demais caminhos que
compartilham enlaces com ele.
"""),

md(r"""
## 5. Ingestão da latência

Os arquivos de latência são delimitados por tabulação e apresentam o valor
`None` nas primeiras amostras, durante a inicialização do `ping`. A conversão
para *epoch* incorpora o deslocamento inferido na Seção 2.

Quanto à implementação, a conversão emprega
`(serie - Timestamp('1970-01-01')) // Timedelta('1s')`, e não
`astype('int64') // 10**9`. O pandas utilizado neste ambiente adota
`datetime64[us]`, e não `[ns]`, de forma que a divisão por `10**9` produziria
valores incorretos sem emissão de erro.
"""),

code(r"""
fg_latencia = fs.ingerir_latencia(alinhamento)

print(f"dimensões: {fg_latencia.shape}")
print("amostras sem medida (inicialização do ping): "
      f"{int(fg_latencia.latencia_ms.isna().sum())}")
fg_latencia.head()
"""),

md(r"""
## 6. Agregação da banda no grão da rota

O atributo `gargalo_Mbps`, definido como a menor banda disponível entre as
interfaces do caminho, constitui a feature central desta etapa, por ser a
grandeza que limita a vazão útil da rota em cada instante.
"""),

code(r"""
fg_banda_rota = fs.agregar_por_rota(fg_banda_interface, topologia)

print(f"dimensões: {fg_banda_rota.shape}")
fg_banda_rota.head()
"""),

md(r"""
## 7. Consolidação e features de janela

A junção emprega a chave `(run_id, rota_id, ts_epoch)`, com `how='left'` a
partir da banda. Os instantes em que o ping não retornou medida permanecem como
`NaN` explícito, preservando a continuidade da série.

### Features de janela deslizante

O valor instantâneo não representa tendência nem estabilidade. Para três
janelas — 5 s (micro), 15 s (curta) e 30 s (longa) — derivam-se as seguintes
grandezas.

Da latência: `p95` (pior caso habitual), `jitter` (desvio padrão, indicador de
instabilidade) e `media`.

Da banda: `gargalo_min` (menor gargalo observado na janela), `banda_media` e
`utilizacao_media`.

### Deltas e features cruzadas

- `latencia_delta_micro_longa` — indicador de tendência; valores positivos e
  crescentes sinalizam congestionamento em formação
- `banda_delta_micro_longa` — severidade do gargalo corrente frente ao
  comportamento típico da coleta
- `bdp` — *Bandwidth-Delay Product* (`gargalo x latencia`), estimativa do
  volume de dados em trânsito

Todas as grandezas acima variam no tempo. Normalizações pela topologia foram
excluídas pelas razões expostas na Seção 3.

> **Observação sobre a janela longa.** A coleta dispõe de aproximadamente 30 s
> úteis, de modo que a janela de 30 s abrange praticamente todo o experimento.
> Ela representa o contexto da própria coleta, e não uma linha de base
> histórica. Em consequência, `latencia_delta_micro_longa` assume valor nulo nos
> primeiros segundos, quando ambas as janelas ainda abrangem as mesmas amostras.
"""),

code(r"""
view = fs.consolidar(fg_banda_rota, fg_latencia)
view = fs.calcular_features_janela(view)
view = fs.calcular_deltas_e_cross_features(view)
view = fs.derivar_alvo(view)

print(f"dimensões da tabela consolidada: {view.shape}")
print("registros com latência e banda simultâneas: "
      f"{int(view.latencia_ms.notna().sum())} de {len(view)}")
print()
view[['datetime_utc', 'rota_id', 'latencia_ms', 'gargalo_Mbps', 'util_max_pct',
      'latencia_jitter_micro_5s', 'bdp']].head(8)
"""),

md(r"""
### A coluna `melhor_rota`

A função `derivar_alvo` produz a coluna `melhor_rota`, correspondente ao índice
(base 1) da rota de menor latência em cada instante, no mesmo formato dos
arquivos `rotulos_*.txt` de `datasets/`, assegurando compatibilidade com o
notebook de aprendizado de máquina.

Cabe uma ressalva quanto a esse alvo. Nos dez conjuntos de dados disponíveis em
`datasets/`, o rótulo corresponde identicamente a `argmin(latencia) + 1` no
mesmo instante, com concordância de `1.0000` em todos eles. O alvo é, portanto,
função determinística de uma das features, e um classificador que receba as
latências resolve um problema trivial. A verificação a seguir documenta esse
resultado.

A feature store não corrige o vazamento. Sua contribuição consiste em
disponibilizar a banda como preditor independente, o que viabiliza formulações
sem vazamento — por exemplo, a previsão da melhor rota em `t + k` a partir das
features observadas em `t`.
"""),

code(r"""
for pasta in sorted(glob.glob('datasets/D*')):
    csvs = glob.glob(os.path.join(pasta, 'latencia_rotas_*.csv'))
    rotulos = glob.glob(os.path.join(pasta, 'rotulos_*.txt')) + \
              glob.glob(os.path.join(pasta, 'labels_*.txt'))
    if not csvs or not rotulos:
        continue
    latencias = pd.read_csv(csvs[0])
    y = np.loadtxt(rotulos[0], dtype=int)
    argmin = latencias.iloc[:, 1:].values.argmin(axis=1) + 1
    n = min(len(y), len(argmin))
    print(f"  {os.path.basename(pasta):5s} n={n:5d}  "
          f"rótulo == argmin(latência): {(y[:n] == argmin[:n]).mean():.4f}")
"""),

md(r"""
## 8. Persistência

A store é gravada em CSV, segundo dois layouts.

O layout **longo** (`data/csv/`) contém um arquivo por feature group, em que
cada registro corresponde a uma observação no grão da respectiva tabela.
Constitui a camada canônica, recuperada por `get_features()`.

O layout **largo** (`data/csv_ml/`) compreende `latencia_rotas_h1_h6.csv`,
`banda_rotas_h1_h6.csv` e `rotulos_h1_h6.txt`, com uma coluna por rota e um
registro por instante. Reproduz o layout de `datasets/D*`, de modo que o
notebook de aprendizado de máquina o consuma sem adaptação.

O layout largo contempla apenas os instantes providos de rótulo, de forma que o
arquivo de features e o de rótulos apresentem contagens iguais de registros —
`np.loadtxt` com `dtype=int` não admite campo vazio.
"""),

code(r"""
gerados = fs.exportar_csv(fg_latencia, fg_banda_interface, fg_banda_rota,
                          view, dim_rota)

for caminho in gerados:
    print(f"  {caminho:52s} {os.path.getsize(caminho):>8,} bytes")
"""),

md(r"""
### 8.1 Precisão e tipos na releitura

O formato CSV não preserva tipos, o que impõe dois cuidados.

Quanto à **precisão**, a escrita é exata: `to_csv` emprega a representação mais
curta que assegura round-trip. A perda ocorre na **leitura**, pois o parser C de
`read_csv` adota, por padrão, uma conversão mais rápida e menos precisa, com
erro na última casa decimal — da ordem de 1e-13 nas colunas de maior magnitude,
como `bdp`.

Quanto aos **tipos**, `datetime_utc` é recuperada como texto e `melhor_rota`
como ponto flutuante, em razão dos valores ausentes.

A função `pipeline.ler_csv` trata ambos os aspectos: aplica
`float_precision='round_trip'` e reconverte as colunas. A comparação a seguir
toma como referência o dataframe em memória.
"""),

code(r"""
numericas = [c for c in view.columns if pd.api.types.is_numeric_dtype(view[c])]


def pior_diferenca(quadro):
    return max(
        (view[c].astype('float64') - quadro[c].astype('float64')).abs().max()
        for c in numericas
    )


padrao = pd.read_csv('feature_store/data/csv/consolidado.csv')
correto = fs.ler_csv('feature_store/data/csv/consolidado.csv')

print(f"read_csv padrão : diferença {pior_diferenca(padrao)}")
print(f"fs.ler_csv      : diferença {pior_diferenca(correto)}")
print()
print("tipos recuperados por fs.ler_csv:")
for coluna in ['ts_epoch', 'datetime_utc', 'melhor_rota', 'rota_id']:
    print(f"  {coluna:14s} memória={str(view[coluna].dtype):16s} "
          f"read_csv={str(padrao[coluna].dtype):10s} ler_csv={correto[coluna].dtype}")

assert pior_diferenca(correto) == 0.0
assert correto.melhor_rota.dtype == 'Int64'
assert pd.api.types.is_datetime64_any_dtype(correto.datetime_utc)
print()
print("ler_csv reproduz os valores e os tipos da tabela em memória.")
"""),

md(r"""
### 8.2 Compatibilidade com o notebook de aprendizado de máquina

A célula seguinte reproduz o procedimento de carga adotado em
`Análise_de_modelos_de_ML_para_previsão_de_caminhos.ipynb` sobre o layout largo
exportado, confirmando que este é consumido sem adaptação.
"""),

code(r"""
historico = pd.read_csv('feature_store/data/csv_ml/latencia_rotas_h1_h6.csv')
rotulos = np.loadtxt('feature_store/data/csv_ml/rotulos_h1_h6.txt',
                     comments='#', dtype=int)

latencia_por_rota = historico.iloc[:, 1:].values
datetimes_dt = pd.to_datetime(historico.iloc[:, 0].values)
temporal_features = np.column_stack([
    datetimes_dt.hour, datetimes_dt.minute, datetimes_dt.second,
    datetimes_dt.day, datetimes_dt.month, datetimes_dt.year,
])

print(f"latencia_por_rota : {latencia_por_rota.shape}")
print(f"temporal_features : {temporal_features.shape}")
print(f"rótulos           : {rotulos.shape}  classes={sorted(set(rotulos.tolist()))}")

assert len(rotulos) == len(historico)
print()
print("As contagens são compatíveis. O layout largo apresenta um registro a")
print("menos que a tabela consolidada, pois o primeiro segundo não dispõe de")
print("medida de latência e, por conseguinte, de rótulo.")
"""),

md(r"""
## 9. Descrição da feature store construída

Apresentam-se, nesta seção, o catálogo das tabelas, o conteúdo da tabela
consolidada, o dicionário de features e a caracterização das rotas.
"""),

code(r"""
catalogo = [
    ('fg_latencia',        'run, rota, ts',            fg_latencia),
    ('fg_banda_interface', 'run, rota, interface, ts', fg_banda_interface),
    ('fg_banda_rota',      'run, rota, ts',            fg_banda_rota),
    ('consolidado',        'run, rota, ts',            view),
    ('dim_rota',           'rota',                     dim_rota),
]

print(f"{'tabela':22s} {'grão':26s} {'registros':>10s} {'colunas':>8s}")
print('-' * 69)
for nome, grao, quadro in catalogo:
    print(f"{nome:22s} {grao:26s} {len(quadro):>10d} {quadro.shape[1]:>8d}")
print('-' * 69)
print(f"{'rotas':22s} {', '.join(sorted(view.rota_id.unique()))}")
print(f"{'janela':22s} {view.datetime_utc.min()} .. {view.datetime_utc.max()} UTC")
print(f"{'duração':22s} {view.tempo_relativo_s.max() + 1} s")
"""),

code(r"""
# Tabela consolidada, na íntegra
view
"""),

code(r"""
# Dicionário de features: tipo, preenchimento e faixa de valores
print(f"consolidado: {len(view)} registros x {view.shape[1]} colunas\n")

descricao = []
for coluna in view.columns:
    serie = view[coluna]
    if pd.api.types.is_numeric_dtype(serie):
        faixa = f"{serie.min():.4g} .. {serie.max():.4g}"
    elif pd.api.types.is_datetime64_any_dtype(serie):
        faixa = f"{serie.min()} .. {serie.max()}"
    else:
        faixa = f"{serie.nunique()} valores distintos"
    descricao.append({
        'coluna': coluna,
        'tipo': str(serie.dtype),
        'preenchidas': f"{serie.notna().sum()}/{len(serie)}",
        'faixa': faixa,
    })

print(pd.DataFrame(descricao).to_string(index=False))
"""),

code(r"""
# Estatísticas descritivas das features que variam no tempo
variaveis = [c for c in view.columns
             if pd.api.types.is_numeric_dtype(view[c])
             and c not in ('run_id', 'ts_epoch', 'tempo_relativo_s', 'melhor_rota')]

view[variaveis].describe().T.round(4)
"""),

code(r"""
# Caracterização das rotas no cenário coletado
retrato = view.groupby('rota_id').agg(
    latencia_media=('latencia_ms', 'mean'),
    latencia_p95=('latencia_ms', lambda s: s.quantile(0.95)),
    jitter_medio=('latencia_jitter_micro_5s', 'mean'),
    gargalo_medio=('gargalo_Mbps', 'mean'),
    gargalo_min=('gargalo_Mbps', 'min'),
    utilizacao_max=('util_max_pct', 'max'),
    bdp_medio=('bdp', 'mean'),
).round(3)
retrato = retrato.join(dim_rota.set_index('rota_id'))
print(retrato.to_string())
"""),

md(r"""
## 10. Verificação

As asserções desta seção documentam os valores esperados e interrompem a
execução em caso de regressão do pipeline.
"""),

code(r"""
# 1. Alinhamento temporal
assert alinhamento['offset_s'] == 25200, alinhamento['offset_s']
assert alinhamento['residuo_s'] == 0, alinhamento['residuo_s']
assert (alinhamento['t_ini'], alinhamento['t_fim']) == (1787019210, 1787019239)

# 2. Contagens por tabela
assert fg_banda_interface.shape[0] == 420, fg_banda_interface.shape   # 14 ifaces x 30 s
assert fg_banda_rota.shape[0] == 120, fg_banda_rota.shape
assert len(view) == 120, len(view)
assert view.rota_id.value_counts().unique().tolist() == [30]

# 3. Cobertura da latência: os valores ausentes concentram-se no primeiro segundo
assert int(view.latencia_ms.notna().sum()) == 116, int(view.latencia_ms.notna().sum())
assert view[view.latencia_ms.isna()].ts_epoch.nunique() == 1

# 4. Ausência de colunas integralmente nulas
assert not [c for c in view.columns if view[c].isna().all()]

print("verificações estruturais: aprovadas")
"""),

code(r"""
# 5. Consistência física: h13_h63 é a única rota disjunta do caminho do iperf
utilizacao = view.groupby('rota_id').util_max_pct.max()
print("utilização máxima por rota (%):")
print(utilizacao.round(3).to_string())

assert utilizacao['h13_h63'] < 0.1, utilizacao['h13_h63']
for rota in ['h11_h61', 'h12_h62', 'h14_h64']:
    assert utilizacao[rota] > 20, (rota, utilizacao[rota])

print()
print("A rota h13_h63 (s1-s4-s5-s6) não compartilha enlaces com o tráfego iperf")
print("e permanece praticamente ociosa. As demais compartilham s1-eth1, s2-eth2")
print("ou s3-eth2 e absorvem a contenção resultante.")
"""),

code(r"""
# 6. Correspondência entre a latência medida e o atraso configurado.
# O atraso configurado é recuperado de dim_rota por junção, por ser atributo da
# rota e não da série temporal.
resumo = view.groupby('rota_id').agg(
    latencia_media=('latencia_ms', 'mean'),
    gargalo_medio=('gargalo_Mbps', 'mean'),
).round(2)
resumo = resumo.join(dim_rota.set_index('rota_id')[['atraso_cfg_ms']])
resumo['folga'] = (resumo.latencia_media - resumo.atraso_cfg_ms).round(2)
print(resumo.to_string())

assert resumo.latencia_media.idxmax() == 'h12_h62'   # maior atraso configurado
print()
print("A rota de maior atraso configurado (h12_h62, 34 ms) apresenta também a")
print("maior latência medida. A folga sobre o valor teórico mantém-se na mesma")
print("ordem de grandeza em todas as rotas, o que indica um custo de")
print("processamento aproximadamente constante somado ao atraso configurado.")
"""),

code(r"""
# 7. Cruzamento com os relatórios de gargalo produzidos pelo protótipo
print("gargalo da tabela consolidada frente a banda_rota_*.txt:")
for rota in sorted(view.rota_id.unique()):
    antigo = pd.read_csv(f'prototipo/relatorios/banda_rota_{rota}.txt', sep='\t',
                         header=None, names=['dt', 'banda'], parse_dates=['dt'])
    antigo['ts_epoch'] = fs.para_epoch(antigo.dt)
    novo = view[view.rota_id == rota][['ts_epoch', 'gargalo_Mbps']]
    casado = novo.merge(antigo[['ts_epoch', 'banda']], on='ts_epoch', how='inner')
    diferenca = 100 * (casado.banda - casado.gargalo_Mbps).abs() / casado.gargalo_Mbps
    print(f"  {rota}: {len(casado)} instantes  "
          f"diferença média {diferenca.mean():.3f}%  máxima {diferenca.max():.3f}%")
    assert len(casado) == 30, len(casado)
    assert diferenca.max() < 2, diferenca.max()

print()
print("A divergência decorre da correção de unidade. O parser do protótipo")
print("divide por 1<<20 (Mibit/s) e subtrai de uma capacidade decimal,")
print("superestimando a banda disponível em 4,86% da taxa medida. Sob carga de")
print("aproximadamente 20 Mbps em enlaces de 100 Mbps, a diferença propaga-se")
print("para cerca de 1,2% no gargalo, e é nula em h13_h63, onde a taxa é")
print("praticamente inexistente.")
"""),

md(r"""
## 11. Visualização de validação
"""),

code(r"""
rota_para_validar = 'h11_h61'
por_interface = fg_banda_interface[fg_banda_interface.rota_id == rota_para_validar]

fig = plt.figure(figsize=(12, 5))
for interface, grupo in por_interface.groupby('interface'):
    tempo = grupo.ts_epoch - view.ts_epoch.min()
    plt.plot(tempo, grupo.taxa_Mbps, label=interface, linewidth=1.5)

plt.legend()
plt.xlabel('Tempo relativo (s)')
plt.ylabel('Taxa total (Mbps)')
plt.title(f'Taxa por interface — rota {rota_para_validar}')
plt.grid(alpha=0.3)
plt.tight_layout()
plt.show()
"""),

code(r"""
# Contraste entre as rotas: gargalo e latência
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

for rota, grupo in view.groupby('rota_id'):
    axes[0].plot(grupo.tempo_relativo_s, grupo.gargalo_Mbps, label=rota, linewidth=1.5)
    axes[1].plot(grupo.tempo_relativo_s, grupo.latencia_ms, label=rota, linewidth=1.5)

axes[0].set_ylabel('Gargalo (Mbps)')
axes[0].set_title('Banda disponível no gargalo do caminho')
axes[0].legend()
axes[0].grid(alpha=0.3)

axes[1].set_ylabel('Latência (ms)')
axes[1].set_xlabel('Tempo relativo (s)')
axes[1].set_title('Latência (RTT)')
axes[1].legend()
axes[1].grid(alpha=0.3)

plt.tight_layout()
plt.show()
"""),

md(r"""
No painel superior, a rota `h13_h63` mantém-se em 100 Mbps, enquanto as demais
decaem para aproximadamente 80 Mbps. O comportamento constitui a assinatura da
contenção de enlaces compartilhados, sinal que se perdia enquanto as duas fontes
permaneciam desalinhadas.
"""),

code(r"""
# Features derivadas: valor instantâneo frente às janelas, jitter, tendência e BDP
da_rota = view[view.rota_id == rota_para_validar]

fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

axes[0].plot(da_rota.tempo_relativo_s, da_rota.latencia_ms,
             label='Latência instantânea', color='darkorange')
axes[0].plot(da_rota.tempo_relativo_s, da_rota.latencia_p95_micro_5s,
             label='P95 (janela 5 s)', color='crimson', linestyle='--')
axes[0].plot(da_rota.tempo_relativo_s, da_rota.latencia_media_longa_30s,
             label='Média (janela 30 s)', color='navy', linestyle=':')
axes[0].set_ylabel('Latência (ms)')
axes[0].set_title(f'Latência instantânea e em janelas — rota {rota_para_validar}')
axes[0].legend()
axes[0].grid(alpha=0.3)

axes[1].plot(da_rota.tempo_relativo_s, da_rota.latencia_jitter_micro_5s,
             label='Jitter (desvio padrão, janela 5 s)', color='purple')
axes[1].plot(da_rota.tempo_relativo_s, da_rota.latencia_delta_micro_longa,
             label='Delta (micro − longa)', color='teal')
axes[1].axhline(0, color='gray', linewidth=0.8)
axes[1].set_ylabel('ms')
axes[1].set_title('Jitter e tendência')
axes[1].legend()
axes[1].grid(alpha=0.3)

axes[2].plot(da_rota.tempo_relativo_s, da_rota.bdp,
             label='BDP (gargalo × latência)', color='darkgreen')
axes[2].set_ylabel('BDP')
axes[2].set_xlabel('Tempo relativo (s)')
axes[2].set_title('Bandwidth-Delay Product')
axes[2].legend()
axes[2].grid(alpha=0.3)

plt.tight_layout()
plt.show()
"""),

md(r"""
## 12. Consulta à store

A função `get_features` recupera a tabela persistida e retorna o subconjunto de
features solicitado. A solicitação restrita a `('latencia',)` reproduz o
conjunto de preditores dos `datasets/D*`, o que permite comparar essa linha de
base com o conjunto que incorpora a banda sem manutenção de pipelines
independentes.
"""),

code(r"""
print("linha de base (somente latência):")
print(f"  {list(fs.get_features(metricas=('latencia',)).columns)}")
print()
print("somente banda:")
print(f"  {list(fs.get_features(metricas=('banda',)).columns)}")
print()
completo = fs.get_features()
print(f"conjunto completo: {completo.shape[1]} colunas, {len(completo)} registros")
"""),

code(r"""
# Filtro por rota e por janela temporal
fs.get_features(
    rotas=['h11_h61', 'h13_h63'],
    inicio='2026-08-18 02:13:35',
    fim='2026-08-18 02:13:38',
)[['datetime_utc', 'rota_id', 'latencia_ms', 'gargalo_Mbps', 'bdp', 'melhor_rota']]
"""),

md(r"""
## 13. Limitações desta coleta

**Volume.** A execução válida compreende 30 s úteis, correspondentes a 120
registros (30 s × 4 rotas). O conjunto é suficiente para validar o pipeline e
evidenciar o efeito da contenção, mas não para treinar um modelo. Resultados de
aprendizado de máquina não devem ser derivados da store em sua configuração
atual.

**Janela longa.** Conforme exposto na Seção 7, a janela de 30 s abrange todo o
experimento e não constitui linha de base histórica.

**Vazamento no alvo.** A coluna `melhor_rota` é função determinística da
latência, conforme demonstrado na Seção 7 para os dez conjuntos de dados
existentes.

**Extensão prevista.** Os conjuntos em `datasets/D*` dispõem de cerca de uma
hora de coleta cada (3600 a 3850 s), com `banda.bwm` cobrindo continuamente as
31 interfaces, sob topologia idêntica à desta coleta — mesmos quatro caminhos e
mesmo `config.json`. Sua ingestão elevaria o conjunto a aproximadamente 36 mil
registros. As funções de `pipeline.py` recebem `pasta_relatorios` e
`caminho_config` como parâmetros precisamente para viabilizar essa extensão sem
reescrita, ainda que `banda.bwm` demande um leitor próprio, dado que agrega
todas as interfaces em um único arquivo, em vez de um arquivo por rota.
"""),
]


def main():
    # nbformat >= 4.5 exige id por celula; sem isso o nbconvert emite
    # MissingIDFieldWarning e versoes futuras falharao
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
