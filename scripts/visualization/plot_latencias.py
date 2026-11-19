import os

import pandas as pd
import numpy as np
from matplotlib import pyplot as plt

rotas = {
    1: { 'cor': '#00bf63', 'nome': 'Verde' },
    2: { 'cor': '#ff3131', 'nome': 'Vermelho' },
    3: { 'cor': '#2440f7', 'nome': 'Azul' },
    4: { 'cor': '#ffd735', 'nome': 'Amarelo' }
}


def datetimes_to_minutes(datetimes, end_time=60.0):
    """Converte array de timestamps para minutos normalizados de 0 a end_time (minutos)."""
    timestamps = pd.to_datetime(datetimes)
    t0 = timestamps[0]
    elapsed_seconds = (timestamps - t0).total_seconds()
    total_seconds = elapsed_seconds[-1]

    # Normaliza para escala 0-end_time independente da duração real
    return (elapsed_seconds / total_seconds) * end_time


def plot_latencias(datetimes, latencias, filename, caminhos, showGraph=True, Y_MAX=150, MAX_COL_WIDTH=800, FIGURE_SIZE=(15, 8), FIGURE_DPI=100):
    pd.set_option('max_colwidth', MAX_COL_WIDTH)
    fig = plt.figure(figsize=FIGURE_SIZE, dpi=FIGURE_DPI)

    # Converte datetimes para minutos desde o início
    minutos = datetimes_to_minutes(datetimes)

    for i in range(len(caminhos)):
        pathId = caminhos[i]
        propriedades = rotas[pathId]
        nome = propriedades["nome"]
        cor = propriedades["cor"]

        # plt.plot(minutos, latencias[:, i], label=f'Caminho {pathId}: {nome}', color=cor, linewidth=1.5)
        plt.plot(minutos, latencias[:, i], label=f'Caminho {pathId}', color=cor, linewidth=1.5)

    # Ticks no eixo X fixos de 0 a 60

    # step = max(1, len(minutos) // 10)
    # tick_positions = minutos[::step]
    # plt.xticks(tick_positions, labels=[f'{v:.1f}' for v in tick_positions], rotation=45, fontsize=22)

    num_ticks = 11  # 0, 6, 12, ..., 60
    tick_positions = np.linspace(minutos[0], minutos[-1], num_ticks)
    tick_labels = np.linspace(0, 60, num_ticks)
    plt.xticks(tick_positions, labels=[f'{v:.0f}' for v in tick_labels], rotation=45, fontsize=22)

    plt.yticks(fontsize=15)

    plt.legend(fontsize=12, title_fontsize=13, loc='upper right')
    plt.xlabel('Tempo (min)', fontsize=15)
    plt.ylabel('Latência (ms)', fontsize=15)
    # plt.title('Latência ao longo do tempo - 1 hora de coleta com tráfego simulado de streaming', fontsize=18)

    plt.ylim(0, Y_MAX)
    plt.tight_layout()

    if filename is not None:
        plt.savefig(filename, dpi=FIGURE_DPI, bbox_inches='tight')

    if showGraph: plt.show()


def main():
    diretorio_dataset = "teste"
    dataset           = ""
    caminho_dataset   = os.path.join(diretorio_dataset, dataset)

    arquivo_latencias = "latencia_rotas_h1_h6.csv"
    arquivo_grafico     = "grafico_latencia.png"

    leituras = pd.read_csv(f'{caminho_dataset}/{arquivo_latencias}')

    datetimes = leituras.iloc[:, 0].values
    latencias = leituras.iloc[:, 1:].values

    # Detecta automaticamente quantos caminhos existem
    num_caminhos = latencias.shape[1]
    rotas = list(range(1, num_caminhos + 1))

    plot_latencias(datetimes, latencias, f"{caminho_dataset}/{arquivo_grafico}", rotas, Y_MAX=latencias.max() * 1.05)

if __name__ == "__main__":
    main()