"""Feature Store de telemetria de rede.

Constroi feature groups a partir dos relatorios gerados pelo prototipo Mininet,
usando a chave de entidade canonica (run_id, rota_id, ts_epoch).

O problema central resolvido aqui e o alinhamento temporal: a latencia e gravada
em hora local pelo prototipo (datetime.fromtimestamp em relatorios.py), enquanto
a banda carrega o epoch do bwm-ng. O offset entre os dois relogios e inferido a
partir de eventos.txt, que registra os instantes BEGIN/END na mesma hora local
da latencia e portanto serve de ponte entre as duas escalas.
"""

import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

# Reusa a definicao de colunas do bwm-ng do parser do prototipo, evitando que as
# duas listas divirjam
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'prototipo'))
from helpers.parser_banda import BWM_NG_COLUNAS

RELATORIOS_PADRAO = 'prototipo/relatorios'
DESTINO_PADRAO = 'feature_store/data'

# Tolerancia do residuo ao inferir o offset de fuso. A premissa e que os dois
# relogios diferem por um numero inteiro de horas; um residuo maior indica que a
# premissa nao se aplica aquela coleta
RESIDUO_MAXIMO_S = 5

_EPOCH = pd.Timestamp('1970-01-01')


def para_epoch(serie):
    """Converte datetime64 para segundos Unix.

    Independente da unidade interna do pandas: astype('int64') assume
    nanossegundos, mas versoes recentes usam datetime64[us] e a divisao por 10**9
    produziria valores silenciosamente errados.
    """
    return (serie - _EPOCH) // pd.Timedelta('1s')


################################################################################
# 1. Alinhamento temporal
################################################################################

def _separar_runs(segundos, gap_maximo_s=1):
    """Rotula runs distintos numa serie de segundos, cortando nos intervalos.

    O bwm-ng abre o arquivo de saida em modo append, entao coletas sucessivas se
    acumulam no mesmo CSV e precisam ser separadas. gap_maximo_s e a maior
    lacuna tolerada como amostra perdida (nao corte de run); nos relatorios do
    prototipo os runs sao separados por dezenas de segundos e o padrao (1s)
    basta, mas o `banda.bwm` dos datasets/D* apresenta ocasionais lacunas de
    1-2s por amostras perdidas do bwm-ng dentro de uma unica coleta continua,
    exigindo tolerancia maior para nao fragmentar indevidamente a serie.
    """
    if len(segundos) == 0:
        return np.array([], dtype=int)
    return np.concatenate([[0], np.cumsum(np.diff(segundos) > gap_maximo_s)])


def inferir_alinhamento(pasta_relatorios=RELATORIOS_PADRAO, arquivo_banda=None, gap_maximo_s=None):
    """Descobre o offset entre os relogios e qual run e o valido.

    Para cada run candidato na fonte de banda, compara a primeira amostra com o
    evento BEGIN de referencia. O -1 compensa o sleep(1) que telemetria.py
    executa entre enfileirar o BEGIN e disparar o bwm-ng.

    arquivo_banda: caminho para um unico CSV do bwm-ng cobrindo todas as
        interfaces (formato `banda.bwm` dos datasets/D*). Quando omitido
        (padrao), usa o primeiro `banda_raw_rota_*.csv` encontrado em
        pasta_relatorios, formato usado pelos relatorios do prototipo.
    gap_maximo_s: tolerancia repassada a _separar_runs. Quando omitido, usa 1s
        para banda_raw_rota_*.csv (runs distintos separados por dezenas de
        segundos) e 5s para arquivo_banda (banda.bwm, onde ha amostras
        perdidas isoladas de 1-2s dentro de uma unica coleta continua).

    O evento de referencia e o BEGIN de banda quando presente. Os datasets/D*
    nao registram esse evento (bwm-ng roda direto, sem fila de eventos), entao
    cai-se para o BEGIN de latencia, que e sincrono o suficiente para o mesmo
    calculo de offset e tolerancia de residuo.

    Retorna dict com offset_s, run_id, t_ini, t_fim e residuo_s.
    """
    eventos = carregar_eventos(pasta_relatorios)
    begin = eventos[(eventos.tipo == 'banda') & (eventos.evento == 'BEGIN')].datahora.min()
    if pd.isna(begin):
        begin = eventos[(eventos.tipo == 'latencia') & (eventos.evento == 'BEGIN')].datahora.min()
    if pd.isna(begin):
        raise ValueError(f'{pasta_relatorios}/eventos.txt nao tem BEGIN de banda nem de latencia')
    begin_ingenuo = para_epoch(pd.Series([begin])).iloc[0]

    if arquivo_banda:
        if not os.path.exists(arquivo_banda):
            raise FileNotFoundError(arquivo_banda)
        bruto = pd.read_csv(arquivo_banda, header=None, usecols=[0])
        if gap_maximo_s is None:
            gap_maximo_s = 5
    else:
        arquivos = sorted(glob.glob(os.path.join(pasta_relatorios, 'banda_raw_rota_*.csv')))
        if not arquivos:
            raise FileNotFoundError(f'nenhum banda_raw_rota_*.csv em {pasta_relatorios}')
        bruto = pd.read_csv(arquivos[0], header=None, usecols=range(len(BWM_NG_COLUNAS)))
        if gap_maximo_s is None:
            gap_maximo_s = 1

    segundos = np.sort(bruto[0].astype(int).unique())
    runs = _separar_runs(segundos, gap_maximo_s)

    candidatos = []
    for run_id in np.unique(runs):
        do_run = segundos[runs == run_id]
        diferenca = (do_run[0] - 1) - begin_ingenuo
        horas = diferenca / 3600
        residuo = abs(horas - round(horas)) * 3600
        candidatos.append({
            'residuo_s': residuo,
            'offset_s': int(round(horas)) * 3600,
            'run_id': int(run_id),
            't_ini': int(do_run[0]),
            't_fim': int(do_run[-1]),
        })

    melhor = min(candidatos, key=lambda c: c['residuo_s'])
    if melhor['residuo_s'] > RESIDUO_MAXIMO_S:
        raise ValueError(
            'nao foi possivel alinhar os relogios: residuo minimo de '
            f"{melhor['residuo_s']:.0f}s excede o limite de {RESIDUO_MAXIMO_S}s. "
            'Os timestamps de latencia e banda podem nao diferir por um numero '
            'inteiro de horas nesta coleta.'
        )
    melhor['candidatos'] = candidatos
    return melhor


def carregar_eventos(pasta_relatorios=RELATORIOS_PADRAO):
    """Le eventos.txt (instantes BEGIN/END de cada coletor, em hora local)."""
    return pd.read_csv(
        os.path.join(pasta_relatorios, 'eventos.txt'),
        sep='\t',
        header=None,
        names=['datahora', 'tipo', 'nome', 'evento'],
        parse_dates=['datahora'],
    )


################################################################################
# 2. Topologia
################################################################################

def carregar_topologia(caminho_config='prototipo/config.json',
                       pasta_relatorios=RELATORIOS_PADRAO):
    """Extrai capacidade por interface, atraso por link e caminho de cada rota.

    A numeracao das interfaces reproduz a ordem dos addLink de topologia.py, que
    e a ordem dos links em config.json. topologia.get_interfaces_links() resolve
    isso de forma mais robusta via Topo.port(), mas exige um objeto Topo vivo e
    portanto nao serve para leitura offline dos relatorios.
    """
    with open(caminho_config) as arquivo:
        topologia = json.load(arquivo)['topologia']

    proxima_porta = {}
    capacidade_por_interface = {}
    # interface, do ponto de vista de quem envia, para cada direcao do link -
    # necessario para resolver, a partir da sequencia de switches de uma rota,
    # qual interface de cada switch aponta para o proximo salto (mesma logica
    # de telemetria.py: switchA.connectionsTo(switchB))
    interface_por_direcao = {}
    for link in topologia['links']:
        a, b = link['pontos']
        porta_a = proxima_porta.get(a, 0) + 1
        proxima_porta[a] = porta_a
        capacidade_por_interface[f'{a}-eth{porta_a}'] = float(link['banda'])
        interface_por_direcao[(a, b)] = f'{a}-eth{porta_a}'

        porta_b = proxima_porta.get(b, 0) + 1
        proxima_porta[b] = porta_b
        capacidade_por_interface[f'{b}-eth{porta_b}'] = float(link['banda'])
        interface_por_direcao[(b, a)] = f'{b}-eth{porta_b}'

    atraso_por_link = {
        tuple(sorted(link['pontos'])): float(link['atraso'] or 0)
        for link in topologia['links']
    }

    rotas = {}
    with open(os.path.join(pasta_relatorios, 'rotas.txt')) as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue
            nome, caminho = linha.split(': ')
            rotas[nome.replace('rota_', '')] = caminho.split('-')

    return {
        'capacidade_por_interface': capacidade_por_interface,
        'interface_por_direcao': interface_por_direcao,
        'atraso_por_link': atraso_por_link,
        'rotas': rotas,
    }


def interfaces_por_rota(topologia):
    """Interfaces (lado de origem) atravessadas por cada rota, na ordem do caminho.

    Reproduz a logica de procAgenteTelemetriaBanda (telemetria.py): para cada
    par consecutivo de switches do caminho, usa a interface do switch de
    origem voltada ao proximo salto. E o mesmo conjunto de interfaces presente
    em banda_tratada_rota_*.csv para cada rota.
    """
    interface_por_direcao = topologia['interface_por_direcao']
    resultado = {}
    for rota_id, caminho in topologia['rotas'].items():
        switches = [no for no in caminho if no.startswith('s')]
        interfaces = []
        for i in range(len(switches) - 1):
            interfaces.append(interface_por_direcao[(switches[i], switches[i + 1])])
        resultado[rota_id] = interfaces
    return resultado


def metadados_das_rotas(topologia):
    """Tabela de dimensao das rotas: atributos fixos do caminho.

    Estes atributos NAO sao features da serie temporal. A topologia nao varia
    durante uma coleta, entao dentro de cada rota eles tem variancia zero e sao
    funcao deterministica de rota_id - um identificador disfarcado de feature.
    Ficam separados da tabela de fatos e podem ser recuperados por join quando
    for preciso comparar rotas entre si.
    """
    linhas = []
    for rota_id, caminho in topologia['rotas'].items():
        switches = [no for no in caminho if no.startswith('s')]
        atraso_ida = sum(
            topologia['atraso_por_link'].get(tuple(sorted((switches[i], switches[i + 1]))), 0)
            for i in range(len(switches) - 1)
        )
        linhas.append({
            'rota_id': rota_id,
            'caminho': '-'.join(caminho),
            'n_links_sw': len(switches) - 1,
            'atraso_cfg_ms': 2 * atraso_ida,
        })
    return pd.DataFrame(linhas).sort_values('rota_id').reset_index(drop=True)


################################################################################
# 3. Ingestao da banda
################################################################################

def ingerir_banda(alinhamento, topologia, pasta_relatorios=RELATORIOS_PADRAO):
    """Le os CSV crus do bwm-ng e monta o feature group por interface.

    Usa banda_raw_* em vez de banda_tratada_* por dois motivos: parser_banda.py
    le o CSV sem header=None e perde a primeira amostra, e converte a taxa para
    Mibit/s (divisao por 1<<20) enquanto a capacidade do TCLink e decimal.
    """
    capacidades = topologia['capacidade_por_interface']
    quadros = []

    for arquivo in sorted(glob.glob(os.path.join(pasta_relatorios, 'banda_raw_rota_*.csv'))):
        rota_id = re.search(r'banda_raw_rota_(.+)\.csv$', os.path.basename(arquivo)).group(1)

        # header=None e essencial: o bwm-ng nao emite cabecalho
        dados = pd.read_csv(
            arquivo,
            header=None,
            usecols=range(len(BWM_NG_COLUNAS)),
            names=BWM_NG_COLUNAS,
        )
        dados = dados[dados.interface != 'total'].copy()

        dados['ts_epoch'] = dados.unix_timestamp.astype(int)
        # Mantem apenas o run identificado como valido
        dados = dados[
            (dados.ts_epoch >= alinhamento['t_ini']) & (dados.ts_epoch <= alinhamento['t_fim'])
        ].copy()

        dados['taxa_Mbps'] = dados.bytes_total_s * 8.0 / 1e6
        dados['capacidade_Mbps'] = dados.interface.map(capacidades)

        sem_capacidade = sorted(set(dados.interface[dados.capacidade_Mbps.isna()]))
        if sem_capacidade:
            raise ValueError(
                f'interfaces sem capacidade em config.json para {rota_id}: {sem_capacidade}'
            )

        dados['banda_disp_Mbps'] = dados.capacidade_Mbps - dados.taxa_Mbps
        dados['util_pct'] = 100 * dados.taxa_Mbps / dados.capacidade_Mbps
        dados['rota_id'] = rota_id
        dados['run_id'] = alinhamento['run_id']

        quadros.append(dados[[
            'run_id', 'rota_id', 'interface', 'ts_epoch',
            'taxa_Mbps', 'capacidade_Mbps', 'banda_disp_Mbps', 'util_pct',
        ]])

    if not quadros:
        raise FileNotFoundError(f'nenhum banda_raw_rota_*.csv em {pasta_relatorios}')

    return (pd.concat(quadros, ignore_index=True)
            .sort_values(['rota_id', 'ts_epoch', 'interface'])
            .reset_index(drop=True))


def ingerir_banda_arquivo_unico(alinhamento, topologia, arquivo_banda):
    """Variante de ingerir_banda para a fonte `banda.bwm` dos datasets/D*.

    Nesses conjuntos o bwm-ng roda uma unica vez monitorando todas as
    interfaces do experimento (nao um processo por rota), produzindo um CSV
    com todas elas misturadas. A funcao filtra apenas as interfaces
    efetivamente percorridas por alguma rota (via interfaces_por_rota) e
    replica cada leitura de interface para todas as rotas que a atravessam -
    interfaces compartilhadas (ex: s1-eth1) aparecem, portanto, em mais de
    uma rota, tal como em ingerir_banda.
    """
    capacidades = topologia['capacidade_por_interface']
    por_rota = interfaces_por_rota(topologia)

    interface_para_rotas = {}
    for rota_id, interfaces in por_rota.items():
        for interface in interfaces:
            interface_para_rotas.setdefault(interface, []).append(rota_id)

    dados = pd.read_csv(
        arquivo_banda,
        header=None,
        usecols=range(len(BWM_NG_COLUNAS)),
        names=BWM_NG_COLUNAS,
    )
    dados = dados[dados.interface.isin(interface_para_rotas)].copy()

    dados['ts_epoch'] = dados.unix_timestamp.astype(int)
    dados = dados[
        (dados.ts_epoch >= alinhamento['t_ini']) & (dados.ts_epoch <= alinhamento['t_fim'])
    ].copy()

    dados['taxa_Mbps'] = dados.bytes_total_s * 8.0 / 1e6
    dados['capacidade_Mbps'] = dados.interface.map(capacidades)
    dados['banda_disp_Mbps'] = dados.capacidade_Mbps - dados.taxa_Mbps
    dados['util_pct'] = 100 * dados.taxa_Mbps / dados.capacidade_Mbps
    dados['run_id'] = alinhamento['run_id']

    quadros = []
    for interface, rotas in interface_para_rotas.items():
        fatia = dados[dados.interface == interface]
        for rota_id in rotas:
            replicado = fatia.copy()
            replicado['rota_id'] = rota_id
            quadros.append(replicado[[
                'run_id', 'rota_id', 'interface', 'ts_epoch',
                'taxa_Mbps', 'capacidade_Mbps', 'banda_disp_Mbps', 'util_pct',
            ]])

    if not quadros:
        raise ValueError(f'nenhuma interface de rota encontrada em {arquivo_banda}')

    return (pd.concat(quadros, ignore_index=True)
            .sort_values(['rota_id', 'ts_epoch', 'interface'])
            .reset_index(drop=True))


################################################################################
# 4. Ingestao da latencia
################################################################################

def ingerir_latencia(alinhamento, pasta_relatorios=RELATORIOS_PADRAO):
    """Le os TXT de latencia e traz os timestamps para a escala do bwm-ng."""
    quadros = []

    for arquivo in sorted(glob.glob(os.path.join(pasta_relatorios, 'latencia_rota_*.txt'))):
        rota_id = re.search(r'latencia_rota_(.+)\.txt$', os.path.basename(arquivo)).group(1)

        dados = pd.read_csv(
            arquivo,
            sep='\t',
            header=None,
            names=['datahora_local', 'latencia_ms'],
            parse_dates=['datahora_local'],
        )
        # As primeiras amostras do ping vem como 'None' enquanto o comando sobe
        dados['latencia_ms'] = pd.to_numeric(dados.latencia_ms, errors='coerce')
        dados['ts_epoch'] = para_epoch(dados.datahora_local) + alinhamento['offset_s']
        dados['rota_id'] = rota_id
        dados['run_id'] = alinhamento['run_id']

        quadros.append(dados[['run_id', 'rota_id', 'ts_epoch', 'latencia_ms']])

    if not quadros:
        raise FileNotFoundError(f'nenhum latencia_rota_*.txt em {pasta_relatorios}')

    return (pd.concat(quadros, ignore_index=True)
            .sort_values(['rota_id', 'ts_epoch'])
            .reset_index(drop=True))


################################################################################
# 5. Agregacao por rota
################################################################################

def agregar_por_rota(fg_banda_interface, topologia):
    """Colapsa a banda por interface em features no grao da rota.

    O gargalo (menor banda disponivel entre as interfaces do caminho) e a feature
    central: e o que limita a vazao util da rota naquele instante.
    """
    # Sem metadados de topologia: eles sao constantes por rota dentro de uma
    # coleta e vivem em dim_rota, nao na tabela de fatos
    return (fg_banda_interface
            .groupby(['run_id', 'rota_id', 'ts_epoch'], as_index=False)
            .agg(gargalo_Mbps=('banda_disp_Mbps', 'min'),
                 banda_media_Mbps=('banda_disp_Mbps', 'mean'),
                 util_max_pct=('util_pct', 'max')))


################################################################################
# 6. Features de janela deslizante
################################################################################

# Janelas usadas como proxy multi-resolucao. A coleta tem ~30s uteis, entao a
# janela 'longa' cobre praticamente todo o experimento: ela nao representa um
# baseline historico, apenas o contexto da propria coleta.
JANELAS_SEGUNDOS = {
    'micro': 5,    # picos rapidos / microbursts
    'curta': 15,   # tendencia de curto prazo
    'longa': 30,   # contexto do experimento
}


def calcular_features_janela(view, janelas=JANELAS_SEGUNDOS):
    """Deriva p95, jitter, media, gargalo e utilizacao por janela deslizante.

    O valor instantaneo nao captura tendencia nem estabilidade; as janelas
    expoem isso. O rolling e temporal (offset em segundos) e nao por numero de
    linhas, para nao silenciar eventuais descontinuidades na serie.
    """
    grupos = []
    for _, grupo in view.groupby('rota_id', sort=False):
        grupo = grupo.sort_values('ts_epoch').copy()
        indexado = grupo.set_index('datetime_utc')

        for nome, largura in janelas.items():
            passo = f'{largura}s'
            latencia = indexado.latencia_ms.rolling(passo, min_periods=1)
            gargalo = indexado.gargalo_Mbps.rolling(passo, min_periods=1)
            media_banda = indexado.banda_media_Mbps.rolling(passo, min_periods=1)
            utilizacao = indexado.util_max_pct.rolling(passo, min_periods=1)

            grupo[f'latencia_p95_{nome}_{largura}s'] = latencia.quantile(0.95).to_numpy()
            grupo[f'latencia_jitter_{nome}_{largura}s'] = latencia.std().to_numpy()
            grupo[f'latencia_media_{nome}_{largura}s'] = latencia.mean().to_numpy()

            grupo[f'gargalo_min_{nome}_{largura}s'] = gargalo.min().to_numpy()
            grupo[f'banda_media_{nome}_{largura}s'] = media_banda.mean().to_numpy()
            grupo[f'utilizacao_media_{nome}_{largura}s'] = (utilizacao.mean() / 100).to_numpy()

        grupos.append(grupo)

    return pd.concat(grupos, ignore_index=True)


def calcular_deltas_e_cross_features(view, janelas=JANELAS_SEGUNDOS):
    """Deltas entre janelas e features cruzadas entre banda e latencia.

    latencia_delta_micro_longa  tendencia: positivo indica congestionamento se
                                formando agora frente ao contexto da coleta
    banda_delta_micro_longa     severidade do gargalo atual frente ao normal
    bdp                         Bandwidth-Delay Product: dados em transito

    Nao inclui normalizacoes pela topologia (latencia por salto, folga sobre o
    RTT teorico). Como a topologia e fixa durante a coleta, essas quantidades
    sao a latencia deslocada ou escalada por uma constante da rota: a
    correlacao com latencia_ms dentro de cada rota e exatamente 1.0, ou seja,
    nao acrescentam informacao. Quem quiser compara-las entre rotas pode
    deriva-las com um join em dim_rota.
    """
    view = view.copy()
    micro, longa = janelas['micro'], janelas['longa']

    view['latencia_delta_micro_longa'] = (
        view[f'latencia_media_micro_{micro}s'] - view[f'latencia_media_longa_{longa}s']
    )
    view['banda_delta_micro_longa'] = (
        view[f'gargalo_min_micro_{micro}s'] / view[f'banda_media_longa_{longa}s']
    )

    # Usa o gargalo, nao a media entre interfaces: e ele que limita a vazao util
    view['bdp'] = view.gargalo_Mbps * view.latencia_ms

    return view


################################################################################
# 7. Consolidacao e persistencia
################################################################################

def consolidar(fg_banda_rota, fg_latencia):
    """Junta banda e latencia pela chave de entidade.

    O join e left a partir da banda: segundos em que o ping falhou permanecem
    como NaN explicito em vez de desaparecerem da serie.
    """
    view = fg_banda_rota.merge(
        fg_latencia,
        on=['run_id', 'rota_id', 'ts_epoch'],
        how='left',
    )
    view['datetime_utc'] = pd.to_datetime(view.ts_epoch, unit='s')
    # Segundos decorridos desde o inicio do run. Serve para plotagem e leitura,
    # nao como chave de juncao: alinhar por tempo relativo casaria o instante 0
    # de cada fonte independentemente do relogio, que e justamente o erro que o
    # offset inferido evita.
    view['tempo_relativo_s'] = view.ts_epoch - view.ts_epoch.min()
    return view.sort_values(['ts_epoch', 'rota_id']).reset_index(drop=True)


def derivar_alvo(view):
    """Adiciona melhor_rota: indice (base 1) da rota de menor latencia no instante.

    Formato identico aos rotulos_*.txt de datasets/, para consumo direto pelo
    notebook de ML.

    ATENCAO: nos 10 datasets de datasets/, o rotulo e identicamente
    argmin(latencia) + 1 no mesmo instante (correspondencia 1.0000 em todos), ou
    seja, o alvo e funcao deterministica de uma das features. Usar esta coluna
    como y reproduz esse vazamento. Ela existe para compatibilidade com o
    baseline, nao como formulacao recomendada.
    """
    view = view.copy()
    rotas_ordenadas = sorted(view.rota_id.unique())
    indice_da_rota = {rota: i + 1 for i, rota in enumerate(rotas_ordenadas)}

    largo = view.pivot_table(index='ts_epoch', columns='rota_id', values='latencia_ms')
    largo = largo.reindex(columns=rotas_ordenadas)

    # Instantes em que alguma rota nao mediu ficam sem rotulo
    completos = largo.dropna()
    melhor = completos.idxmin(axis=1).map(indice_da_rota)

    view['melhor_rota'] = view.ts_epoch.map(melhor).astype('Int64')
    return view


################################################################################
# Persistencia (CSV)
################################################################################

# Colunas da view que precisam de conversao explicita na releitura, ja que o CSV
# nao carrega tipos
COLUNAS_DATA = ['datetime_utc']
COLUNAS_INTEIRO_NULAVEL = ['melhor_rota']


def exportar_csv(fg_latencia, fg_banda_interface, fg_banda_rota, view,
                 dim_rota=None, pasta_destino=DESTINO_PADRAO):
    """Persiste a store em CSV, em dois layouts.

    Longo: um CSV por feature group, mais dim_rota.csv com os atributos fixos
    de cada caminho. Cada linha de um feature group e uma observacao no grao da
    tabela. E a camada canonica, lida de volta por get_features().

    Largo: latencia_rotas_h1_h6.csv, banda_rotas_h1_h6.csv e rotulos_h1_h6.txt,
    com uma coluna por rota e uma linha por instante - o mesmo layout de
    datasets/D*, para que o notebook de ML leia sem adaptacao.

    O CSV nao carrega tipos, entao datas saem em ISO 8601 e o ts_epoch e
    preservado como inteiro, o que permite releitura exata sem depender de
    parsing de data.

    A escrita e exata: o to_csv do pandas usa a repr mais curta que faz
    round-trip. O risco esta na LEITURA - o parser C do read_csv usa, por
    padrao, uma conversao mais rapida e menos precisa, que introduz erro na
    ultima casa (~1e-13 nas colunas de maior magnitude). Use ler_csv() abaixo,
    ou passe float_precision='round_trip' ao read_csv.
    """
    pasta_longo = os.path.join(pasta_destino, 'csv')
    pasta_largo = os.path.join(pasta_destino, 'csv_ml')
    os.makedirs(pasta_longo, exist_ok=True)
    os.makedirs(pasta_largo, exist_ok=True)

    gerados = []

    # --- layout longo: espelho dos feature groups + dimensao ---
    tabelas = [('fg_latencia', fg_latencia),
               ('fg_banda_interface', fg_banda_interface),
               ('fg_banda_rota', fg_banda_rota),
               ('consolidado', view)]
    if dim_rota is not None:
        tabelas.append(('dim_rota', dim_rota))

    for nome, quadro in tabelas:
        caminho = os.path.join(pasta_longo, f'{nome}.csv')
        quadro.to_csv(caminho, index=False, date_format='%Y-%m-%dT%H:%M:%S')
        gerados.append(caminho)

    # --- layout largo: compativel com datasets/D* ---
    # Apenas instantes com rotulo, para que o CSV de features e o TXT de rotulos
    # tenham o mesmo numero de linhas (np.loadtxt com dtype=int nao aceita vazio)
    com_rotulo = view[view.melhor_rota.notna()]

    def para_largo(coluna):
        largo = com_rotulo.pivot_table(index='datetime_utc', columns='rota_id', values=coluna)
        largo.index.name = 'timestamp'
        return largo.reset_index()

    latencia_larga = para_largo('latencia_ms')
    banda_larga = para_largo('gargalo_Mbps')

    caminho_latencia = os.path.join(pasta_largo, 'latencia_rotas_h1_h6.csv')
    caminho_banda = os.path.join(pasta_largo, 'banda_rotas_h1_h6.csv')
    latencia_larga.to_csv(caminho_latencia, index=False, date_format='%Y-%m-%d %H:%M:%S')
    banda_larga.to_csv(caminho_banda, index=False, date_format='%Y-%m-%d %H:%M:%S')
    gerados += [caminho_latencia, caminho_banda]

    rotulos = (com_rotulo.groupby('datetime_utc').melhor_rota.first()
               .astype(int).sort_index())
    caminho_rotulos = os.path.join(pasta_largo, 'rotulos_h1_h6.txt')
    with open(caminho_rotulos, 'w') as arquivo:
        for valor in rotulos:
            arquivo.write(f'{valor}\n')
    gerados.append(caminho_rotulos)

    if len(rotulos) != len(latencia_larga):
        raise ValueError(
            f'rotulos ({len(rotulos)}) e features ({len(latencia_larga)}) '
            'com contagens diferentes'
        )

    return gerados


def ler_csv(caminho, **kwargs):
    """Le um CSV da store restaurando precisao e tipos.

    float_precision='round_trip' e obrigatorio: o padrao do parser C do pandas
    erra na ultima casa decimal. As colunas de data e de inteiro nulavel sao
    reconvertidas, ja que o CSV as entrega como texto e float.
    """
    kwargs.setdefault('float_precision', 'round_trip')
    quadro = pd.read_csv(caminho, **kwargs)

    for coluna in COLUNAS_DATA:
        if coluna in quadro.columns:
            quadro[coluna] = pd.to_datetime(quadro[coluna])
    for coluna in COLUNAS_INTEIRO_NULAVEL:
        if coluna in quadro.columns:
            quadro[coluna] = quadro[coluna].astype('Int64')

    return quadro


################################################################################
# 7. Recuperacao
################################################################################

def get_features(rotas=None, metricas=('latencia', 'banda'), inicio=None, fim=None,
                 incluir_dim_rota=False, pasta_origem=DESTINO_PADRAO):
    """Recupera features da store, opcionalmente filtrando rotas e janela.

    rotas: lista de rota_id, ou None para todas
    metricas: quais grupos incluir - 'latencia', 'banda' ou ambos
    inicio, fim: limites temporais, como epoch int, string ou pd.Timestamp
    incluir_dim_rota: junta os atributos fixos do caminho (caminho, n_links_sw,
        atraso_cfg_ms). Fora por padrao: sao constantes por rota durante a
        coleta e portanto funcao deterministica de rota_id. Ligue quando o uso
        for comparar rotas entre si, nao alimentar um modelo com rota_id.

    Pedir apenas ('latencia',) reproduz o conjunto de features dos datasets D*,
    permitindo comparar o baseline contra latencia+banda sem manter dois
    pipelines.
    """
    if isinstance(metricas, str):
        metricas = (metricas,)
    metricas = tuple(metricas)
    desconhecidas = set(metricas) - {'latencia', 'banda'}
    if desconhecidas:
        raise ValueError(f'metricas desconhecidas: {sorted(desconhecidas)}')

    view = ler_csv(os.path.join(pasta_origem, 'csv', 'consolidado.csv'))

    chaves = ['run_id', 'rota_id', 'ts_epoch', 'datetime_utc', 'tempo_relativo_s']
    # As features cruzadas combinam as duas metricas, entao so fazem sentido
    # quando ambas foram pedidas
    cruzadas = ['bdp', 'banda_delta_micro_longa']

    def eh_de_latencia(coluna):
        return coluna.startswith('latencia_')

    def eh_de_banda(coluna):
        return (coluna.startswith(('gargalo_', 'banda_', 'utilizacao_'))
                or coluna == 'util_max_pct')

    selecionadas = [c for c in chaves if c in view.columns]
    for coluna in view.columns:
        if coluna in selecionadas or coluna in cruzadas or coluna == 'melhor_rota':
            continue
        if eh_de_latencia(coluna) and 'latencia' in metricas:
            selecionadas.append(coluna)
        elif eh_de_banda(coluna) and 'banda' in metricas:
            selecionadas.append(coluna)

    if len(metricas) == 2:
        selecionadas += [c for c in cruzadas if c in view.columns]
    if 'melhor_rota' in view.columns:
        selecionadas.append('melhor_rota')

    resultado = view[selecionadas]

    if incluir_dim_rota:
        dim = ler_csv(os.path.join(pasta_origem, 'csv', 'dim_rota.csv'))
        resultado = resultado.merge(dim, on='rota_id', how='left')

    if rotas is not None:
        resultado = resultado[resultado.rota_id.isin(rotas)]
    if inicio is not None:
        resultado = resultado[resultado.ts_epoch >= _limite_para_epoch(inicio)]
    if fim is not None:
        resultado = resultado[resultado.ts_epoch <= _limite_para_epoch(fim)]

    return resultado.sort_values(['ts_epoch', 'rota_id']).reset_index(drop=True)


def _limite_para_epoch(valor):
    """Aceita epoch int, string de data ou Timestamp como limite de janela."""
    if isinstance(valor, (int, np.integer)):
        return int(valor)
    return int(para_epoch(pd.Series([pd.Timestamp(valor)])).iloc[0])


################################################################################
# Orquestracao
################################################################################

def construir(pasta_relatorios=RELATORIOS_PADRAO,
              caminho_config='prototipo/config.json',
              pasta_destino=DESTINO_PADRAO,
              persistir_em_disco=True,
              arquivo_banda=None):
    """Executa o pipeline completo e devolve as tabelas construidas.

    arquivo_banda: quando informado (caminho para um `banda.bwm`, formato dos
        datasets/D*), a banda e ingerida a partir desse arquivo unico via
        ingerir_banda_arquivo_unico, em vez dos banda_raw_rota_*.csv de
        pasta_relatorios. Usado para reconstruir a store sobre datasets/D*, que
        nao produzem um CSV por rota.
    """
    alinhamento = inferir_alinhamento(pasta_relatorios, arquivo_banda=arquivo_banda)
    topologia = carregar_topologia(caminho_config, pasta_relatorios)

    if arquivo_banda:
        fg_banda_interface = ingerir_banda_arquivo_unico(alinhamento, topologia, arquivo_banda)
    else:
        fg_banda_interface = ingerir_banda(alinhamento, topologia, pasta_relatorios)
    fg_latencia = ingerir_latencia(alinhamento, pasta_relatorios)
    fg_banda_rota = agregar_por_rota(fg_banda_interface, topologia)
    dim_rota = metadados_das_rotas(topologia)

    view = consolidar(fg_banda_rota, fg_latencia)
    view = calcular_features_janela(view)
    view = calcular_deltas_e_cross_features(view)
    view = derivar_alvo(view)

    if persistir_em_disco:
        exportar_csv(fg_latencia, fg_banda_interface, fg_banda_rota, view,
                     dim_rota, pasta_destino)

    return {
        'alinhamento': alinhamento,
        'topologia': topologia,
        'dim_rota': dim_rota,
        'fg_latencia': fg_latencia,
        'fg_banda_interface': fg_banda_interface,
        'fg_banda_rota': fg_banda_rota,
        'view': view,
    }
