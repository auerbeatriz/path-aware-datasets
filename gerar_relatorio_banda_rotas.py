import glob
import json
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(RAIZ, 'prototipo'))

from helpers.parser_banda import (
    capacidadeInterfaces,
    interfacesDoCaminho,
    carregarBandaConsolidada,
    parseBandaCaminho,
)

################################################################################
# Lê o arquivo rotas.txt de um cenário e retorna a lista de rotas
#   Formato de cada linha: 'nome: h11-s1-s2-s3-s6-h61'
#
def parseRotas(arquivo):
    rotas = []
    with open(arquivo) as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            nome, caminho_str = linha.split(':', 1)
            caminho = caminho_str.strip().split('-')
            rotas.append({'nome': nome.strip(), 'caminho': caminho})
    return rotas

################################################################################
# Gera os relatórios de banda por caminho (banda_<rota>.txt) de um cenário,
#   extraindo os dados do arquivo consolidado banda.bwm
#
def gerarRelatoriosBanda(pasta):
    arquivo_bwm = os.path.join(pasta, 'banda.bwm')
    arquivo_config = os.path.join(pasta, 'config.json')
    arquivo_rotas = os.path.join(pasta, 'rotas.txt')

    if not (os.path.isfile(arquivo_bwm) and os.path.isfile(arquivo_config) and os.path.isfile(arquivo_rotas)):
        return

    with open(arquivo_config) as f:
        config = json.load(f)
    links = config['topologia']['links']
    capacidade_por_interface, interface_no_link = capacidadeInterfaces(links)

    rotas = parseRotas(arquivo_rotas)
    data = carregarBandaConsolidada(arquivo_bwm)

    for rota in rotas:
        interfaces = interfacesDoCaminho(rota['caminho'], interface_no_link)
        parseBandaCaminho(rota['nome'], interfaces, data, capacidade_por_interface, pasta_saida=pasta)
        print(f"[{os.path.basename(pasta)}] banda_{rota['nome']}.txt gerado ({len(interfaces)} interfaces)")

def main():
    for pasta in sorted(glob.glob(os.path.join(RAIZ, 'datasets', '*'))):
        if os.path.isdir(pasta):
            gerarRelatoriosBanda(pasta)

if __name__ == '__main__':
    main()
