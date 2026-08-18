import msg
from datetime import datetime
from helpers.parser_banda import parseBanda

################################################################################
# Salva o histórico de telemetria de banda por caminho em arquivos texto
#
# Parâmetros:
#   topologia - estrutura carregada de config.json
# Retorno:
#   None
#
def salvarRelatorioBanda(topologia):
    # Cria uma coluna com a banda disponível no link
    proxima_porta = {}
    capacidade_por_interface = {}
    for link in topologia['links']:
        capacidade = link.get('banda')
        for ponto in link['pontos']:
            porta = proxima_porta.get(ponto, 0) + 1
            proxima_porta[ponto] = porta
            capacidade_por_interface[f'{ponto}-eth{porta}'] = float(capacidade)
    
    # Parse de relatórios de banda por caminho
    for rota in topologia['rotas']:
        parseBanda(rota, topologia, capacidade_por_interface)

################################################################################
# Salva o histórico de telemetria e dados de teste em arquivos texto
#
# Parâmetros:
#   resultado - dicionário contendo todos os dados obtidos pelo servidor contendo
#       telemetria e resultado dos testes de vazão
# Retorno:
#   None
#
def arquivosSalvar(resultado, topologia):
    # Telemetria armazenada e dados de vazão
    valores = resultado['valores']

    for tipo, lista_nomes in valores.items():
        for nome, lista in lista_nomes.items():
            f = open(f'relatorios/{tipo}_{nome}.txt', 'w')
            for tempo, valor in lista.items():
                if type(tempo) == str:
                    ftempo = float(tempo)
                else:
                    ftempo = tempo
                ts_datahora = datetime.fromtimestamp(ftempo)
                datahora = ts_datahora.strftime("%Y-%m-%d %H:%M:%S")
                if valor == None:
                    svalor = 'None'
                else:
                    svalor = str(valor)
                f.write('%s\t%s\n' % (datahora, svalor))
            f.close()

    salvarRelatorioBanda(topologia)
    
    # Eventos registrados durante os testes
    eventos = resultado['eventos']
    # Colocando em orgem cronológica
    eventos.sort(key=lambda item: item['datahora'])
    f = open(f'relatorios/eventos.txt', 'w')
    for item in eventos:
        datahora = item['datahora']
        tipo = item['tipo']
        nome = item['nome']
        evento = item['evento']
        f.write('%s\t%s\t%s\t%s\n' % (datahora, tipo, nome, evento))
    f.close()
    # Rotas
    rotas = resultado['rotas']
    f = open(f'relatorios/rotas.txt', 'w')
    for item in rotas:
        nome = item['nome']
        caminho = '-'.join(item['caminho'])
        f.write('%s: %s\n' % (nome, caminho))
    f.close()
    msg.info("Resultados salvos em arquivos na pasta 'relatorios'.")
    return None
