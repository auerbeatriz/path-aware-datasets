import pandas as pd
import numpy as np
from matplotlib import pyplot as plt

import warnings
warnings.filterwarnings("ignore")

pd.set_option('max_colwidth', 800)

arq_latencias = '60min_iperf/latencia_rotas_h1_h6.csv'
ard_rotulos = ''

routes = {
    1: { 'cor': '#00bf63', 'nome': 'Verde' },
    2: { 'cor': '#ff3131', 'nome': 'Vermelho' },
    3: { 'cor': '#2440f7', 'nome': 'Azul' },
    4: { 'cor': '#ffd735', 'nome': 'Amarelo' }
}

def plot_latencias(datetimes, latencias, filename, caminhos):
    fig = plt.figure(figsize=(15, 8))

    for i in range(len(caminhos)):
        pathId = caminhos[i]
        propriedades = routes[pathId]
        nome = propriedades["nome"]
        cor = propriedades["cor"]

        plt.plot(datetimes, latencias[:, i], label=f'Caminho {pathId}: {nome}', color=cor, linewidth=1.5)

    step = max(1, len(datetimes) // 10)  # mostra +- 10 datas no eixo
    plt.xticks(datetimes[::step], rotation=45)

    plt.legend()
    plt.xlabel('Data/Hora')
    plt.ylabel('Latência (ms)')
    plt.title('Latência ao longo do tempo')
    plt.xticks(rotation=45)
    plt.tight_layout()

    if filename != None:
        plt.savefig(filename)
    
    plt.show()

def main():
    pd.set_option('max_colwidth', 800)

    leituras = pd.read_csv(arq_latencias)
    #rotulos = np.loadtxt(ard_rotulos, comments='#', dtype=int)

    datetimes = leituras.iloc[:, 0].values
    latencias = leituras.iloc[:, 1:].values

    print(latencias[3000:])

    plot_latencias(datetimes[3000:], latencias[3000:])

if __name__ == "__main__":
    main()