"""
plot_matrizes_confusao.py
=========================
Lê um arquivo summary.txt e gera gráficos de matriz de confusão.

Configurações disponíveis (edite a seção CONFIG abaixo):
  - MODELOS_PLOTAR  : lista dos modelos a plotar (None = todos)
  - TAMANHO_FONTE   : tamanho base dos textos da imagem
  - DIRETORIO_SAIDA : diretório de saída para salvar os gráficos
  - FORMATO_SAIDA   : formato do arquivo ('png', 'pdf', 'svg', etc.)
  - DPI             : resolução da imagem salva
  - EXIBIR_GRAFICOS : exibir os gráficos em janela interativa
  - COLORMAP        : colormap do matplotlib (ex: 'YlGnBu', 'Blues', 'viridis')
"""

import re
import os
import sys
import argparse
import numpy as np
import matplotlib.pyplot as plt

CONFIG = {
    # Modelos a plotar. Use None para plotar todos os encontrados no arquivo.
    "MODELOS_PLOTAR": ["DecisionTree", "RandomForest", "SVC", "GaussianNB"],

    # Tamanho base dos textos (título, eixos, rótulos, valores da célula).
    "TAMANHO_FONTE": 22,

    # Diretório onde os gráficos serão salvos. Use None para não salvar.
    "DIRETORIO_SAIDA": "./matrizes_confusao",

    # Formato de saída: 'png', 'pdf', 'svg', 'jpg', etc.
    "FORMATO_SAIDA": "png",

    # Resolução (DPI) dos arquivos salvos.
    "DPI": 300,

    # True  → exibe cada gráfico em janela interativa.
    # False → apenas salva (útil em servidores sem display).
    "EXIBIR_GRAFICOS": False,

    # Colormap do heatmap. Sugestões: 'YlGnBu', 'Blues', 'Greens', 'viridis'.
    "COLORMAP": "YlGnBu",
}


def ler_summary(caminho_arquivo: str) -> dict:
    """
    Lê o arquivo summary.txt e retorna um dicionário com os dados de cada modelo:
        {
            "NomeModelo": {
                "matriz_confusao": np.ndarray,
                "rotulos_classe":  list[str],
                "acuracia":        float | None,
            },
            ...
        }
    """
    with open(caminho_arquivo, "r", encoding="utf-8") as arquivo:
        conteudo = arquivo.read()

    modelos = {}

    padrao_bloco = re.compile(
        r"Modelo:\s*(\S+)\s*\n"
        r"[\s\S]*?"
        r"(?=Modelo:\s*\S|\Z)",
        re.MULTILINE,
    )

    for bloco in padrao_bloco.finditer(conteudo):
        nome_modelo = bloco.group(1).strip()
        texto_bloco = bloco.group(0)

        # Extrai rótulos de classe do Relatório de Classificação
        padrao_rotulos = re.compile(
            r"^\s{0,12}(\S+)\s+\d+\.\d+\s+\d+\.\d+\s+\d+\.\d+\s+\d+",
            re.MULTILINE,
        )
        rotulos_brutos = padrao_rotulos.findall(texto_bloco)
        rotulos_classe = [
            r for r in rotulos_brutos
            if r.lower() not in ("accuracy", "macro", "weighted")
        ]

        # Extrai a Matriz de Confusão
        padrao_matriz = re.compile(
            r"Matriz de Confus[aã]o:\s*\n((?:\s*\[.*?\]\s*\n?)+)",
            re.IGNORECASE,
        )
        resultado_matriz = padrao_matriz.search(texto_bloco)

        if not resultado_matriz:
            print(f"[AVISO] Matriz de confusão não encontrada para '{nome_modelo}'. Pulando.")
            continue

        texto_matriz = resultado_matriz.group(1)
        linhas = re.findall(r"\[([\d\s]+)\]", texto_matriz)

        try:
            matriz = np.array([[int(v) for v in linha.split()] for linha in linhas])
        except ValueError:
            print(f"[AVISO] Falha ao converter matriz de '{nome_modelo}'. Pulando.")
            continue

        # Gera rótulos genéricos se não encontrou nenhum
        if not rotulos_classe:
            rotulos_classe = [str(i + 1) for i in range(matriz.shape[0])]

        modelos[nome_modelo] = {
            "matriz_confusao": matriz,
            "rotulos_classe":  rotulos_classe,
        }

    # Extrai acurácia do Relatório Resumido
    padrao_acuracia = re.compile(r"(\S+)\s+\|\s+Acc:\s+([\d.]+)")
    for resultado in padrao_acuracia.finditer(conteudo):
        nome, acuracia = resultado.group(1), float(resultado.group(2))
        if nome in modelos:
            modelos[nome]["acuracia"] = acuracia

    return modelos


def _anotar_celulas(ax, matriz: np.ndarray, tamanho_fonte: float) -> None:
    """Escreve o valor numérico no centro de cada célula da matriz."""
    for i in range(matriz.shape[0]):
        for j in range(matriz.shape[1]):
            ax.text(
                j, i, str(matriz[i, j]),
                ha="center", va="center",
                fontsize=tamanho_fonte,
                color="black",
            )


def plotar_matriz_confusao(
    matriz: np.ndarray,
    rotulos_classe: list,
    nome_modelo: str,
    acuracia: float | None = None,
    tamanho_fonte: int = 12,
    colormap: str = "YlGnBu",
    diretorio_saida: str | None = None,
    formato_saida: str = "png",
    dpi: int = 150,
    exibir: bool = True,
) -> None:
    """Gera e (opcionalmente) salva/exibe o gráfico de matriz de confusão."""

    tamanho_titulo    = tamanho_fonte
    tamanho_eixo      = tamanho_fonte
    tamanho_marcacao  = tamanho_fonte - 4
    tamanho_celula    = tamanho_fonte - 4
    tamanho_colorbar  = tamanho_fonte - 1

    fig, ax = plt.subplots(figsize=(6, 5))

    imagem = ax.matshow(matriz, cmap=plt.get_cmap(colormap), alpha=0.85)

    barra_cor = fig.colorbar(imagem, ax=ax, fraction=0.046, pad=0.04)
    barra_cor.ax.tick_params(labelsize=tamanho_colorbar)

    _anotar_celulas(ax, matriz, tamanho_fonte=tamanho_celula)

    marcacoes = range(len(rotulos_classe))
    ax.set_xticks(list(marcacoes))
    ax.set_yticks(list(marcacoes))
    ax.set_xticklabels(rotulos_classe, fontsize=tamanho_marcacao)
    ax.set_yticklabels(rotulos_classe, fontsize=tamanho_marcacao)

    ax.tick_params(top=False, bottom=True, labeltop=False, labelbottom=True)
    ax.set_xlabel("Predito", fontsize=tamanho_eixo, labelpad=8)
    ax.set_ylabel("Real",    fontsize=tamanho_eixo, labelpad=8)

    titulo = nome_modelo
    if acuracia is not None:
        titulo += f"\nAcurácia: {acuracia:.4f}"
    ax.set_title(titulo, fontsize=tamanho_titulo, pad=14)

    plt.tight_layout()

    if diretorio_saida:
        os.makedirs(diretorio_saida, exist_ok=True)
        nome_arquivo = f"matriz_confusao_{nome_modelo}.{formato_saida}"
        caminho_saida = os.path.join(diretorio_saida, nome_arquivo)
        fig.savefig(caminho_saida, dpi=dpi, bbox_inches="tight")
        print(f"  Salvo: {caminho_saida}")

    if exibir:
        plt.show()

    plt.close(fig)



def main():
    cenario = '1'
    dataset = 'D1'
    pasta_resultados = f"resultados_am/Cenario{cenario}_{dataset}"

    parser = argparse.ArgumentParser(
        description="Gera matrizes de confusão a partir de um arquivo summary.txt.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "arquivo_summary",
        nargs="?",
        default=pasta_resultados + "summary.txt",
        help="Caminho para o arquivo summary.txt (padrão: summary.txt)",
    )
    parser.add_argument(
        "--modelos", "-m",
        nargs="+",
        metavar="MODELO",
        default=None,
        help=(
            "Nomes dos modelos a plotar (separados por espaço).\n"
            "Se omitido, usa CONFIG['MODELOS_PLOTAR'].\n"
            "Se CONFIG também for None, plota todos os modelos encontrados.\n"
            "Exemplo: --modelos LogisticRegression DecisionTree"
        ),
    )
    parser.add_argument(
        "--tamanho-fonte", "-f",
        type=int,
        default=None,
        metavar="N",
        help="Tamanho base dos textos. Se omitido, usa CONFIG['TAMANHO_FONTE'].",
    )
    parser.add_argument(
        "--diretorio-saida", "-o",
        default=None,
        metavar="DIR",
        help="Diretório de saída (sobrescreve CONFIG['DIRETORIO_SAIDA']).",
    )
    parser.add_argument(
        "--sem-exibicao",
        action="store_true",
        help="Não exibe janelas interativas; apenas salva os arquivos.",
    )
    parser.add_argument(
        "--listar",
        action="store_true",
        help="Lista os modelos disponíveis no arquivo e encerra.",
    )

    args = parser.parse_args()

    # Carregar e validar o arquivo
    if not os.path.isfile(args.arquivo_summary):
        print(f"[ERRO] Arquivo não encontrado: '{args.arquivo_summary}'")
        sys.exit(1)

    print(f"\nLendo: {args.arquivo_summary}")
    todos_modelos = ler_summary(args.arquivo_summary)

    if not todos_modelos:
        print("[ERRO] Nenhum modelo com matriz de confusão encontrado no arquivo.")
        sys.exit(1)

    # listar
    if args.listar:
        print("\nModelos disponíveis no arquivo:")
        for nome, dados in todos_modelos.items():
            acuracia = dados.get("acuracia")
            sufixo = f"  |  Acurácia: {acuracia:.4f}" if acuracia is not None else ""
            print(f"  • {nome}{sufixo}")
        sys.exit(0)

    # Resolver configurações (CLI > CONFIG > padrão)
    filtro_modelos  = args.modelos        or CONFIG.get("MODELOS_PLOTAR")
    tamanho_fonte   = args.tamanho_fonte  or CONFIG.get("TAMANHO_FONTE", 12)
    diretorio_saida = args.diretorio_saida or CONFIG.get("DIRETORIO_SAIDA")
    exibir_graficos = not args.sem_exibicao and CONFIG.get("EXIBIR_GRAFICOS", True)
    formato_saida   = CONFIG.get("FORMATO_SAIDA", "png")
    dpi             = CONFIG.get("DPI", 150)
    colormap        = CONFIG.get("COLORMAP", "YlGnBu")

    # Filtrar modelos
    if filtro_modelos:
        modelos_selecionados = {}
        for nome in filtro_modelos:
            if nome in todos_modelos:
                modelos_selecionados[nome] = todos_modelos[nome]
            else:
                print(f"[AVISO] Modelo '{nome}' não encontrado no arquivo. Ignorando.")
        if not modelos_selecionados:
            print("[ERRO] Nenhum dos modelos solicitados foi encontrado.")
            sys.exit(1)
    else:
        modelos_selecionados = todos_modelos

    # Gerar gráficos
    print(f"\nGerando {len(modelos_selecionados)} gráfico(s)...\n")

    for nome_modelo, dados in modelos_selecionados.items():
        print(f"→ {nome_modelo}")
        plotar_matriz_confusao(
            matriz          = dados["matriz_confusao"],
            rotulos_classe  = dados["rotulos_classe"],
            nome_modelo     = nome_modelo,
            acuracia        = dados.get("acuracia"),
            tamanho_fonte   = tamanho_fonte,
            colormap        = colormap,
            diretorio_saida = diretorio_saida,
            formato_saida   = formato_saida,
            dpi             = dpi,
            exibir          = exibir_graficos,
        )

    print("\nConcluído!")


if __name__ == "__main__":
    main()