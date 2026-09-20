"""Protocolo de avaliacao temporal para a previsao da melhor rota.

Reune o que nao depende da origem dos dados: deslocar o alvo no tempo, cortar
treino e teste cronologicamente e montar o quadro de entrada a partir dos CSVs
consolidados de datasets/. E consumido tanto pela feature store
(feature_store/pipeline.py, que reexporta as funcoes deste modulo) quanto pelo
notebook de analise de modelos, que usa apenas os CSVs de latencia ou de banda.

O contrato entre as duas pontas e um unico quadro "largo": uma linha por
instante, com

    <chave_grupo>   identificador da coleta, para que o fim de um dataset nunca
                    case com o inicio de outro (por padrao 'dataset_id')
    <coluna_tempo>  instante em segundos inteiros (por padrao 'ts_epoch')
    features        uma coluna por rota, ou por (metrica, rota)
    <coluna_alvo>   id da melhor rota naquele instante (por padrao 'melhor_rota')

De onde vem esse quadro e escolha de quem chama:

    feature store - pipeline.construir_wide(features_longas, colunas_feature),
                    que pivota as features longas por rota_id
    datasets/D*   - largo_de_csv(...) deste modulo, que le um CSV consolidado
                    (latencia_rotas_h1_h6.csv ou banda_rotas_h1_h6.csv) mais o
                    TXT de rotulos

Nenhuma funcao daqui olha para nomes de coluna especificos de uma das fontes:
as chaves sao parametros e as features sao "todas as outras colunas".
"""

import os

import numpy as np
import pandas as pd

CHAVE_GRUPO_PADRAO = 'dataset_id'
COLUNA_TEMPO_PADRAO = 'ts_epoch'
COLUNA_ALVO_PADRAO = 'melhor_rota'

# Nome da coluna com o alvo contemporaneo, preservado por deslocar_alvo para que
# o baseline de persistencia possa ser medido nas mesmas linhas de teste
COLUNA_ALVO_ATUAL = 'alvo_atual'

# Prefixo das colunas de feature por metrica, na mesma convencao de
# pipeline.construir_wide ('<metrica>__<rota>'), inferido do nome do arquivo
PREFIXO_POR_METRICA = {
    'latencia': 'latencia_ms',
    'banda': 'banda_Mbps',
}
PREFIXO_GENERICO = 'metrica'

_EPOCH = pd.Timestamp('1970-01-01')


################################################################################
# Escala de tempo
################################################################################

def para_epoch(serie):
    """Converte datetime64 para segundos Unix.

    Independente da unidade interna do pandas: astype('int64') assume
    nanossegundos, mas versoes recentes usam datetime64[us] e a divisao por 10**9
    produziria valores silenciosamente errados.
    """
    return (serie - _EPOCH) // pd.Timedelta('1s')


################################################################################
# Montagem do quadro largo a partir dos CSVs consolidados
################################################################################

def prefixo_do_arquivo(caminho):
    """Deduz o prefixo das colunas de feature pelo nome do arquivo.

    'latencia_rotas_h1_h6.csv' -> 'latencia_ms'
    'banda_rotas_h1_h6.csv'    -> 'banda_Mbps'
    qualquer outro             -> 'metrica'
    """
    nome = os.path.basename(str(caminho)).lower()
    for chave, prefixo in PREFIXO_POR_METRICA.items():
        if nome.startswith(chave):
            return prefixo
    return PREFIXO_GENERICO


def largo_de_csv(caminho_csv, caminho_rotulos=None, grupo=None, prefixo=None,
                 chave_grupo=CHAVE_GRUPO_PADRAO, coluna_tempo=COLUNA_TEMPO_PADRAO,
                 coluna_alvo=COLUNA_ALVO_PADRAO, tolerancia_borda=5, verboso=True):
    """Monta o quadro largo a partir de um CSV consolidado por rota.

    Funciona para qualquer CSV no formato 'timestamp na primeira coluna, uma
    coluna por rota nas demais', o que cobre latencia_rotas_h1_h6.csv e
    banda_rotas_h1_h6.csv sem tratamento especial.

    Parametros:
        caminho_csv      - CSV consolidado (timestamp + uma coluna por rota)
        caminho_rotulos  - TXT com o id da melhor rota por linha. Quando None, o
                           quadro volta sem a coluna de alvo e quem chama precisa
                           acrescenta-la antes de usar deslocar_alvo
        grupo            - valor de chave_grupo. Por padrao, o nome da pasta do
                           CSV (ex.: 'datasets/D2/...' -> 'D2')
        prefixo          - prefixo das colunas de feature. Por padrao, inferido
                           do nome do arquivo (ver prefixo_do_arquivo)
        tolerancia_borda - diferenca aceitavel, em linhas, entre o CSV e o TXT de
                           rotulos. Uma ou duas linhas vem de borda de
                           alinhamento entre coletas; muitas indicam
                           desalinhamento real e levantam ValueError
    Retorno:
        DataFrame largo, com indice reiniciado
    """
    caminho_csv = str(caminho_csv)
    if grupo is None:
        grupo = os.path.basename(os.path.dirname(os.path.abspath(caminho_csv)))
    if prefixo is None:
        prefixo = prefixo_do_arquivo(caminho_csv)

    leituras = pd.read_csv(caminho_csv)
    instantes = pd.to_datetime(leituras.iloc[:, 0])

    largo = pd.DataFrame({
        chave_grupo: grupo,
        coluna_tempo: para_epoch(instantes).to_numpy(),
    })
    for coluna in leituras.columns[1:]:
        largo[f'{prefixo}__{coluna}'] = leituras[coluna].to_numpy(dtype=float)

    if caminho_rotulos is not None:
        rotulos = np.loadtxt(str(caminho_rotulos), comments='#', dtype=int)
        rotulos = np.atleast_1d(rotulos)

        if len(largo) != len(rotulos):
            diferenca = abs(len(largo) - len(rotulos))
            if diferenca > tolerancia_borda:
                raise ValueError(
                    f'{caminho_csv}: o CSV tem {len(largo)} linhas e os rotulos '
                    f'{len(rotulos)} (diferenca de {diferenca}, maior que a '
                    f'tolerancia de borda de {tolerancia_borda})'
                )
            if verboso:
                print(f'[{grupo}] truncando {diferenca} linha(s) de borda')
            tamanho_comum = min(len(largo), len(rotulos))
            largo = largo.iloc[:tamanho_comum]
            rotulos = rotulos[:tamanho_comum]

        largo[coluna_alvo] = rotulos

    # Instantes repetidos duplicariam linhas no casamento t -> t+H
    repetidos = int(largo[coluna_tempo].duplicated().sum())
    if repetidos:
        raise ValueError(
            f'{caminho_csv}: {repetidos} instante(s) repetido(s) em {coluna_tempo}'
        )

    antes = len(largo)
    largo = largo.dropna()
    if verboso and len(largo) != antes:
        print(f'[{grupo}] descartando {antes - len(largo)}/{antes} linha(s) com NaN')

    return largo.reset_index(drop=True)


def colunas_de_feature(largo, chave_grupo=CHAVE_GRUPO_PADRAO,
                       coluna_tempo=COLUNA_TEMPO_PADRAO,
                       coluna_alvo=COLUNA_ALVO_PADRAO, prefixo=None):
    """Lista as colunas de feature de um quadro largo.

    Sao todas as que nao sao chave nem alvo, de modo que o mesmo codigo serve
    para um quadro da feature store (dezenas de colunas por rota) e para um
    quadro de uma unica metrica. Com `prefixo`, restringe a uma metrica
    especifica (ex.: prefixo='latencia_ms' em um quadro que junta as duas).
    """
    reservadas = {chave_grupo, coluna_tempo, coluna_alvo, COLUNA_ALVO_ATUAL,
                  'run_id', 'rota_id', 'datetime_utc', 'tempo_relativo_s'}
    colunas = [coluna for coluna in largo.columns if coluna not in reservadas]
    if prefixo is not None:
        colunas = [coluna for coluna in colunas if coluna.startswith(f'{prefixo}__')]
    return colunas


################################################################################
# Deslocamento do alvo e corte cronologico
################################################################################

def deslocar_alvo(largo, horizonte_s, coluna_alvo=COLUNA_ALVO_PADRAO,
                  chave_grupo=CHAVE_GRUPO_PADRAO, coluna_tempo=COLUNA_TEMPO_PADRAO):
    """Converte a tarefa contemporanea em preditiva: y(t) passa a ser o alvo
    observado em t + horizonte_s, mantendo X com informacao apenas ate t.

    O deslocamento e feito por casamento explicito de timestamp (t + H), nao
    por `shift(-H)` posicional: a serie tem lacunas (segundos sem medida, ou
    descartados no pivot por rota incompleta), entao deslocar N linhas
    apontaria para um instante arbitrario, nem sempre H segundos a frente.
    Linhas cujo instante t + H nao existe na serie sao descartadas.

    O deslocamento e feito dentro de cada grupo (`chave_grupo`, tipicamente o
    dataset), para nao casar o fim de um dataset com o inicio de outro.

    Devolve uma copia com `coluna_alvo` substituida pelo alvo futuro e uma
    coluna adicional `alvo_atual` com o valor contemporaneo - necessaria para
    calcular o baseline de persistencia (prever que a melhor rota daqui a H
    segundos e a mesma de agora).
    """
    if horizonte_s <= 0:
        raise ValueError('horizonte_s deve ser positivo')

    quadro = largo.copy()
    chaves = [c for c in ([chave_grupo] if chave_grupo else []) if c in quadro.columns]

    futuro = quadro[chaves + [coluna_tempo, coluna_alvo]].copy()
    futuro[coluna_tempo] = futuro[coluna_tempo] - horizonte_s
    futuro = futuro.rename(columns={coluna_alvo: '_alvo_futuro'})

    quadro = quadro.rename(columns={coluna_alvo: COLUNA_ALVO_ATUAL})
    quadro = quadro.merge(futuro, on=chaves + [coluna_tempo], how='left')

    antes = len(quadro)
    quadro = quadro.dropna(subset=['_alvo_futuro'])
    descartadas = antes - len(quadro)
    if descartadas:
        print(f"deslocar_alvo(H={horizonte_s}s): descartando {descartadas}/{antes} "
              f"linha(s) sem observacao em t+{horizonte_s}s")

    quadro = quadro.rename(columns={'_alvo_futuro': coluna_alvo})
    return quadro.reset_index(drop=True)


def split_temporal(largo, fracao_treino=0.8, lacuna_s=0,
                   chave_grupo=CHAVE_GRUPO_PADRAO, coluna_tempo=COLUNA_TEMPO_PADRAO):
    """Corte cronologico treino/teste, com lacuna entre os dois blocos.

    Substitui o `train_test_split(..., shuffle=True)`, que embaralha os
    instantes e coloca vizinhos temporais (quase identicos, dada a
    autocorrelacao da serie) simultaneamente em treino e teste - inflando a
    acuracia por vazamento, nao por capacidade preditiva.

    O corte e feito por grupo (dataset): cada dataset contribui com seus
    primeiros `fracao_treino` instantes para o treino e os ultimos para o
    teste. Cortar globalmente por epoch colocaria datasets inteiros de um
    lado so, transformando o teste em generalizacao entre coletas.

    lacuna_s: segundos descartados entre o fim do treino e o inicio do teste.
    Deve ser >= o horizonte de previsao, para que nenhum alvo de treino
    (observado em t + H) caia dentro da janela de teste.

    Devolve (indice_treino, indice_teste) como mascaras booleanas alinhadas a
    `largo`.
    """
    chaves = [c for c in ([chave_grupo] if chave_grupo else []) if c in largo.columns]

    treino = pd.Series(False, index=largo.index)
    teste = pd.Series(False, index=largo.index)

    grupos = largo.groupby(chaves).indices if chaves else {None: largo.index.values}
    for _, posicoes in grupos.items():
        bloco = largo.iloc[posicoes] if chaves else largo
        tempos = np.sort(bloco[coluna_tempo].unique())
        corte = tempos[int(len(tempos) * fracao_treino)]
        rotulos = bloco.index
        treino.loc[rotulos[bloco[coluna_tempo] <= corte]] = True
        teste.loc[rotulos[bloco[coluna_tempo] > corte + lacuna_s]] = True

    return treino, teste


def preparar_treino_teste(largo, horizonte_s, fracao_treino=0.8, lacuna_s=None,
                          coluna_alvo=COLUNA_ALVO_PADRAO,
                          chave_grupo=CHAVE_GRUPO_PADRAO,
                          coluna_tempo=COLUNA_TEMPO_PADRAO):
    """Aplica o protocolo completo: deslocamento do alvo e corte cronologico.

    E a composicao que os dois notebooks fazem, extraida para um lugar so.

    horizonte_s = 0 reproduz a tarefa contemporanea, mas ja com corte
    cronologico: nesse caso o alvo nao e deslocado e `alvo_atual` recebe o
    proprio alvo, de modo que o baseline de persistencia da 1.0 por construcao.

    lacuna_s: por padrao igual a horizonte_s, que e o minimo necessario para que
    nenhum alvo de treino caia no bloco de teste.

    Retorno:
        (quadro, treino, teste) - o quadro com o alvo ja deslocado e as duas
        mascaras booleanas alinhadas a ele
    """
    quadro = largo.reset_index(drop=True)

    if horizonte_s > 0:
        quadro = deslocar_alvo(
            quadro, horizonte_s, coluna_alvo=coluna_alvo,
            chave_grupo=chave_grupo, coluna_tempo=coluna_tempo,
        )
    else:
        quadro = quadro.assign(**{COLUNA_ALVO_ATUAL: quadro[coluna_alvo]})

    if lacuna_s is None:
        lacuna_s = horizonte_s

    treino, teste = split_temporal(
        quadro, fracao_treino=fracao_treino, lacuna_s=lacuna_s,
        chave_grupo=chave_grupo, coluna_tempo=coluna_tempo,
    )

    return quadro, treino, teste
