"""Lógica da tela "Importar extrato" (sem Streamlit, para poder ser testada).

O `app.py` só desenha o `RelatorioImportacao` devolvido aqui. Nada neste módulo
altera o leiaute exportado para o Fortes nem a regra de idempotência: a
importação continua sendo feita por `Motor.importar`.

Ordem de `processar_importacao`: validar o envio, ler o arquivo numa cópia
temporária e só então guardar o original e criar o lote. Arquivo inválido não
deixa rastro em `dados/<empresa>/arquivos` nem no banco.
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from . import empresas
from .leitores import ler_extrato
from .modelo import Status

EXTENSOES_ACEITAS: tuple[str, ...] = (".ofx", ".ofc", ".csv", ".txt", ".xlsx", ".pdf")
TAMANHO_MAXIMO: int = 20 * 1024 * 1024  # bytes (20 MB)

_GENERICO = (
    "Confira se o arquivo é o extrato da empresa e envie de novo; se persistir, "
    "guarde o arquivo e avise o responsável pelo sistema."
)


@dataclass
class RelatorioImportacao:
    ok: bool
    titulo: str
    detalhe: str
    o_que_fazer: str
    lidas: int = 0
    novas: int = 0
    ja_importadas: int = 0
    liberados: int = 0
    pendentes: int = 0
    bloqueados: int = 0
    total_entradas: Decimal = Decimal("0")
    total_saidas: Decimal = Decimal("0")
    primeira_data: date | None = None
    ultima_data: date | None = None
    avisos: list[str] = field(default_factory=list)
    lote_id: int | None = None


def formatar_moeda(valor: Decimal) -> str:
    """'R$ 1.234,56' e '-R$ 300,00', sempre com Decimal."""
    v = Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    texto = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {texto}"


def _nome_seguro(nome: str) -> str:
    """Só o nome do arquivo, nunca caminho (aceita barras de Windows e Unix)."""
    return Path(str(nome).replace("\\", "/")).name


def _recusa(titulo: str, detalhe: str, o_que_fazer: str) -> RelatorioImportacao:
    return RelatorioImportacao(ok=False, titulo=titulo, detalhe=detalhe, o_que_fazer=o_que_fazer)


def validar_envio(nome: str, conteudo: bytes) -> RelatorioImportacao | None:
    """Checagens antes de ler. Devolve relatório com ok=False, ou None se passou."""
    nome = _nome_seguro(nome)
    sufixo = Path(nome).suffix.lower()
    aceitas = ", ".join(EXTENSOES_ACEITAS)
    if sufixo not in EXTENSOES_ACEITAS:
        tipo = f"do tipo {sufixo}" if sufixo else "sem extensão"
        return _recusa(
            "Arquivo não importado",
            f"O arquivo {nome} é {tipo}, que o sistema não lê.",
            f"Envie o extrato em um destes formatos: {aceitas}. "
            "O ideal é o OFX baixado no internet banking.",
        )
    if len(conteudo) == 0:
        return _recusa(
            "Arquivo não importado",
            f"O arquivo {nome} está vazio (0 bytes).",
            "Baixe o extrato de novo no internet banking e confira se o arquivo abre antes de enviar.",
        )
    if len(conteudo) > TAMANHO_MAXIMO:
        mb = len(conteudo) / (1024 * 1024)
        return _recusa(
            "Arquivo não importado",
            f"O arquivo {nome} tem {f'{mb:.1f}'.replace('.', ',')} MB e o limite é "
            f"{TAMANHO_MAXIMO // (1024 * 1024)} MB.",
            "Baixe o extrato por períodos menores (por exemplo, um mês por vez) e envie um de cada vez.",
        )
    return None


def traduzir_erro(nome: str, erro: Exception) -> RelatorioImportacao:
    """Mensagem para a pessoa do escritório, sem traceback."""
    nome = _nome_seguro(nome)
    sufixo = Path(nome).suffix.lower()
    msg = str(erro).strip()
    baixa = msg.lower()
    titulo = "Arquivo não importado"

    def pronto(detalhe: str, o_que_fazer: str) -> RelatorioImportacao:
        return _recusa(titulo, detalhe, o_que_fazer)

    if isinstance(erro, UnicodeDecodeError):
        return pronto(
            f"Não foi possível ler os caracteres do arquivo {nome} (codificação desconhecida).",
            "Salve o arquivo como UTF-8 ou exporte o extrato de novo no banco.",
        )
    if isinstance(erro, (zipfile.BadZipFile, ET.ParseError)):
        if sufixo == ".xlsx":
            return pronto(
                f"O arquivo {nome} não é uma planilha .xlsx válida.",
                "Exporte a planilha de novo em formato .xlsx (Excel) ou use o OFX do banco.",
            )
        return pronto(
            f"O arquivo {nome} está corrompido ou incompleto.",
            "Baixe o extrato de novo no internet banking e envie o arquivo novo.",
        )
    if isinstance(erro, OSError):
        return pronto(
            f"Não foi possível abrir o arquivo {nome}.",
            "Envie o arquivo de novo; se persistir, guarde o arquivo e avise o responsável pelo sistema.",
        )
    if isinstance(erro, ValueError):
        # Os leitores já escrevem em português e citam a linha; reaproveitamos a mensagem.
        detalhe = msg or f"O arquivo {nome} não pôde ser lido."
        if sufixo in (".ofx", ".ofc"):
            return pronto(detalhe, "Baixe o OFX de novo no internet banking e envie o arquivo novo.")
        if "linha" in baixa and ("sem valor" in baixa or "inválid" in baixa):
            return pronto(detalhe, "Corrija a linha citada no arquivo e envie de novo, ou baixe o extrato novamente no banco.")
        if "data inválida" in baixa or "data ofx inválida" in baixa or "valor monetário inválido" in baixa \
                or "fração de centavo" in baixa:
            return pronto(
                detalhe,
                "Corrija a data ou o valor citado (ou a linha indicada) e envie de novo, "
                "ou baixe o extrato novamente no banco.",
            )
        if "sem cabeçalho" in baixa or "coluna" in baixa or "cabeçalho" in baixa or "colunas" in baixa:
            return pronto(
                detalhe,
                "Exporte o extrato de novo do banco em CSV com cabeçalho, com as colunas "
                "data, histórico e valor.",
            )
        if sufixo in (".ofx", ".ofc") or "ofx" in baixa:
            return pronto(
                detalhe,
                "Baixe o OFX de novo no internet banking e envie o arquivo novo.",
            )
        if sufixo == ".xlsx" or "planilha" in baixa or ".xlsx" in baixa:
            return pronto(
                detalhe,
                "Envie um .xlsx com uma única planilha de movimentação (cabeçalho com data e valor), "
                "ou use o OFX do banco.",
            )
        if sufixo == ".pdf" or "pdf" in baixa or "saldo" in baixa or "itaú" in baixa:
            return pronto(
                detalhe,
                "Só é aceito o extrato do Itaú no modelo Entradas e Saídas. "
                "Baixe o PDF de novo no internet banking, sem editar, e envie.",
            )
        if "sem transa" in baixa or "nenhum movimento" in baixa:
            return pronto(detalhe, "Baixe o extrato de novo, escolhendo um período que tenha movimentação.")
        return pronto(detalhe, _GENERICO)
    return pronto(f"Não foi possível processar o arquivo {nome}.", _GENERICO)


def _sem_transacoes(nome: str) -> RelatorioImportacao:
    sufixo = Path(nome).suffix.lower()
    if sufixo in (".ofx", ".ofc"):
        return _recusa(
            "Arquivo não importado",
            f"O arquivo {nome} foi lido, mas não tem nenhuma transação.",
            "Baixe o OFX de novo no internet banking, escolhendo um período com movimentação.",
        )
    return _recusa(
        "Arquivo não importado",
        f"O arquivo {nome} foi lido, mas não tem nenhuma transação.",
        "Baixe o extrato de novo, escolhendo um período com movimentação, e confira o cabeçalho "
        "(data, histórico e valor).",
    )


def processar_importacao(motor, empresa, nome: str, conteudo: bytes) -> RelatorioImportacao:
    """Valida, lê, guarda o original e importa. Erro de arquivo vira relatório com ok=False."""
    nome = _nome_seguro(nome)
    if recusado := validar_envio(nome, conteudo):
        return recusado

    # 2) leitura prévia numa cópia temporária; nada é gravado na pasta da empresa.
    try:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / nome
            caminho.write_bytes(conteudo)
            transacoes = ler_extrato(caminho, empresa.conta_bancaria)
    except (ValueError, UnicodeDecodeError, zipfile.BadZipFile, ET.ParseError, OSError) as erro:
        return traduzir_erro(nome, erro)
    except Exception as erro:  # leitor de PDF/XLSX com erro inesperado: sem traceback na tela
        if Path(nome).suffix.lower() == ".pdf":
            return _recusa(
                "Arquivo não importado",
                f"O arquivo {nome} não parece ser um PDF válido ou está danificado.",
                "Só é aceito o extrato do Itaú no modelo Entradas e Saídas. "
                "Baixe o PDF de novo no internet banking, sem editar, e envie.",
            )
        return _recusa(
            "Arquivo não importado",
            f"O arquivo {nome} não pôde ser lido ({type(erro).__name__}).",
            _GENERICO,
        )
    if not transacoes:
        return _sem_transacoes(nome)

    # 3) só agora o arquivo é guardado e o lote é criado.
    try:
        original, _repetido = empresas.guardar_original(empresa, nome, conteudo)
        resultado = motor.importar(original, empresa.conta_bancaria)
    except (ValueError, UnicodeDecodeError, zipfile.BadZipFile, ET.ParseError, OSError) as erro:
        return traduzir_erro(nome, erro)

    # 4) relatório
    por_status = resultado.por_status
    liberados = por_status.get(Status.LIBERADO, 0)
    pendentes = por_status.get(Status.PENDENTE, 0)
    bloqueados = por_status.get(Status.BLOQUEADO, 0)
    datas = [t.data for t in transacoes]

    avisos: list[str] = []
    if resultado.arquivo_ja_visto_no_lote:
        avisos.append(
            f"Este arquivo idêntico já tinha sido importado no lote {resultado.arquivo_ja_visto_no_lote}."
        )
    if resultado.novas == 0:
        avisos.append("Nenhuma transação nova: todas as linhas deste arquivo já estavam no sistema.")
    if pendentes > 0:
        avisos.append(f"{pendentes} lançamento(s) pendente(s): revise na seção 2.")
    if bloqueados > 0:
        avisos.append(
            f"{bloqueados} lançamento(s) bloqueado(s): corrija a conta ou descarte na seção 2."
        )

    if resultado.novas == 0:
        titulo = "Nada de novo neste extrato"
        detalhe = (
            f"Foram lidas {resultado.lidas} transações de {nome}, e todas já estavam no sistema. "
            "Nenhum lançamento foi criado."
        )
    else:
        titulo = "Extrato importado"
        detalhe = (
            f"Foram lidas {resultado.lidas} transações de {nome}: "
            f"{resultado.novas} nova(s) e {resultado.ja_importadas} já importada(s) antes."
        )
    if resultado.novas == 0:
        o_que_fazer = "Confira se este é o período certo; se já importou este extrato, não há nada a fazer."
    elif pendentes or bloqueados:
        o_que_fazer = "Revise os lançamentos pendentes e bloqueados na seção 2 antes de exportar."
    else:
        o_que_fazer = ""
    if resultado.arquivo_ja_visto_no_lote and resultado.novas > 0:
        o_que_fazer = o_que_fazer or "Confira se o arquivo não foi enviado em duplicidade."

    return RelatorioImportacao(
        ok=True,
        titulo=titulo,
        detalhe=detalhe,
        o_que_fazer=o_que_fazer,
        lidas=resultado.lidas,
        novas=resultado.novas,
        ja_importadas=resultado.ja_importadas,
        liberados=liberados,
        pendentes=pendentes,
        bloqueados=bloqueados,
        total_entradas=resultado.total_entradas,
        total_saidas=resultado.total_saidas,
        primeira_data=min(datas),
        ultima_data=max(datas),
        avisos=avisos,
        lote_id=resultado.lote_id,
    )
