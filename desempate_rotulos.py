import random
from collections import deque
from datetime import datetime

FORMATOS_TIMESTAMP = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f')

################################################################################
# Utilitários compartilhados pelos geradores de rótulo (gerar_rotulos_banda.py,
#   gerar_rotulos_latencia.py e gerar_historico_fluxo.py) para o desempate
#   entre rotas com valores praticamente iguais no mesmo instante:
#
#   1. candidatas = rotas com EXATAMENTE o melhor valor do instante (empate
#      só entre valores realmente iguais);
#   2. entre elas, a de melhor média na janela de 'janela_segundos' ANTERIORES
#      ao instante (o próprio instante fica fora; sem dados no passado, a rota
#      não tem média);
#   3. se as médias também forem exatamente iguais ou nenhuma candidata tiver
#      passado, sorteio com gerador de semente fixa.
#
#   A janela só olha o passado para que o rótulo possa ser reproduzido de
#   forma causal (nada do futuro do instante entra na decisão).
#

def parse_timestamp(texto):
    for formato in FORMATOS_TIMESTAMP:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise ValueError(f"Timestamp em formato inesperado: {texto!r}")

def parse_valor(texto):
    if texto in ('', 'None'):
        return None
    try:
        return float(texto)
    except ValueError:
        return None

def medias_janela_passado(timestamps, linhas_valores, janela_segundos):
    """
    Para cada linha i, média de cada coluna sobre as linhas j com
    t_i - janela_segundos <= t_j < t_i (estritamente anteriores), ignorando
    valores ausentes. None onde a coluna não tem valor no passado da janela.
    As linhas devem estar em ordem cronológica.
    """
    num_colunas = max((len(valores) for valores in linhas_valores), default=0)
    somas = [0.0] * num_colunas
    contagens = [0] * num_colunas
    fila = deque()
    resultado = []

    for i, (instante, valores) in enumerate(zip(timestamps, linhas_valores)):
        while fila and (instante - timestamps[fila[0]]).total_seconds() > janela_segundos:
            antigo = fila.popleft()
            for k, valor in enumerate(linhas_valores[antigo]):
                if valor is not None:
                    somas[k] -= valor
                    contagens[k] -= 1

        resultado.append([somas[k] / contagens[k] if contagens[k] else None for k in range(num_colunas)])

        fila.append(i)
        for k, valor in enumerate(valores):
            if valor is not None:
                somas[k] += valor
                contagens[k] += 1

    return resultado

def novo_gerador_aleatorio(semente):
    return random.Random(semente)

def novas_estatisticas():
    return {'linhas': 0, 'sem_valor': 0, 'empates_instante': 0, 'por_media': 0, 'sorteios': 0}

def escolher_rota(valores, minimizar, medias, rng, estatisticas):
    """
    Retorna o ID (1-indexado) da melhor rota em 'valores' (floats ou None),
    aplicando o desempate descrito no cabeçalho. 'medias' são as médias da
    janela passada de cada rota (None sem dados). Atualiza 'estatisticas'.
    """
    estatisticas['linhas'] += 1

    validos = [(i, v) for i, v in enumerate(valores) if v is not None]
    if not validos:
        # Sem nenhum valor no instante: mantém o fallback histórico (rota 1)
        estatisticas['sem_valor'] += 1
        return 1

    melhor = min(v for _, v in validos) if minimizar else max(v for _, v in validos)
    candidatas = [i for i, v in validos if v == melhor]

    if len(candidatas) == 1:
        return candidatas[0] + 1

    estatisticas['empates_instante'] += 1

    com_media = [i for i in candidatas if medias[i] is not None]
    if com_media:
        melhor_media = min(medias[i] for i in com_media) if minimizar else max(medias[i] for i in com_media)
        empatadas = [i for i in com_media if medias[i] == melhor_media]
    else:
        empatadas = candidatas

    if len(empatadas) == 1:
        estatisticas['por_media'] += 1
        return empatadas[0] + 1

    estatisticas['sorteios'] += 1
    return rng.choice(empatadas) + 1

def resumo_estatisticas(estatisticas):
    n = estatisticas['linhas'] or 1
    return (f"{estatisticas['linhas']} linhas | empates no instante: {estatisticas['empates_instante']} "
            f"({100 * estatisticas['empates_instante'] / n:.1f}%) -> por média da janela: {estatisticas['por_media']}, "
            f"sorteados: {estatisticas['sorteios']} | sem valor: {estatisticas['sem_valor']}")

def ler_csv_consolidado_para_rotulo(caminho_entrada):
    """Lê 'timestamp,rota1,...,rotaN' e retorna (timestamps, linhas_valores)."""
    timestamps, linhas_valores = [], []
    with open(caminho_entrada, 'r') as entrada:
        entrada.readline()  # Descarta cabeçalho
        for linha in entrada:
            linha = linha.strip()
            if not linha:
                continue
            partes = linha.split(',')
            if len(partes) < 2:
                continue
            timestamps.append(parse_timestamp(partes[0]))
            linhas_valores.append([parse_valor(valor) for valor in partes[1:]])
    return timestamps, linhas_valores
