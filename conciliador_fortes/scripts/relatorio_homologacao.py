"""Gera a matriz de rastreabilidade e o relatório de homologação da P-004.

    python scripts/relatorio_homologacao.py [--data-dir PASTA] [--saida PASTA_DOCS]

1. Roda a suíte pytest (testes AUTOMATIZADOS) e lê o resultado real de cada teste.
2. Confere que todo teste citado na matriz existe.
3. Lê, na central.db informada, o último registro de cada item que depende da
   instalação real do Fortes. Sem registro com evidência, o item sai como
   "NÃO TESTADO". Este script nunca marca um item de instalação real como aprovado.

Saídas: matriz-rastreabilidade.md e relatorio-homologacao.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
from domain import homologacao as hom  # noqa: E402
from storage.database import conectar_central  # noqa: E402

# (requisito, item P-004, diretriz, testes automatizados, o que só a instalação real prova)
MATRIZ = [
    ("R1 Integração com o Fortes não é dada como validada sem importação real", "H1", "1",
     ["test_aut_hom_01_h1_exige_lote_aceito_e_conferido", "test_aut_hom_01b_regras_gerais"],
     "Importar um lote no Fortes de teste e conferir o Razão exportado (procedimento H1)"),
    ("R2 Conferência do lote no Razão depois da importação (ausente, duplicado, valor, conta)", "H1", "1, 5",
     ["test_aut_dup_03_conferencia_pos_importacao_aprova", "test_aut_dup_03_conferencia_pos_importacao_detecta"],
     "O Razão real do Fortes ter o formato que o leitor entende (H3)"),
    ("R3 Limite do histórico configurável (40 a 250) e auditado", "H2", "2",
     ["test_aut_hist_01_limite_configuravel_e_faixa"], "Descobrir o limite que o Fortes aceita (procedimento H2)"),
    ("R4 Histórico original preservado; marca nunca cortada; corte só no arquivo", "H2", "2, 5",
     ["test_aut_hist_02_historico_completo_preservado", "test_aut_hist_03_mudar_limite_nao_altera_lote_gerado"],
     "Fortes não rejeitar nem cortar o histórico no limite escolhido"),
    ("R5 Razão não é tratado como compatível sem arquivo real (aviso e flag na conferência)", "H3", "3",
     ["test_aut_raz_01_conferencia_provisoria_sem_homologacao"], "Carregar um Razão real e comparar o saldo (procedimento H3)"),
    ("R6 Backup e restauração em pasta isolada, com relatório verificável", "H4", "4",
     ["test_aut_bk_01_restauracao_isolada", "test_aut_bk_02_restauracao_detecta_original_corrompido",
      "test_backup_e_restauracao", "test_backup_corrompido_e_detectado"],
     "Rodar scripts/teste_restauracao.py na base do escritório (procedimento H4)"),
    ("R7 Duplicidade: arquivo, FITID, semelhança, marca já no Razão, igual a lote anterior", "H1", "5",
     ["test_arquivo_repetido_bloqueado_e_fitid_alerta", "test_semelhanca_entre_arquivos_tabulares",
      "test_aut_dup_01_marca_ja_no_razao_bloqueia", "test_aut_dup_02_igual_a_lote_aceito_sem_decisao_bloqueia"],
     "Confirmar no Fortes que uma segunda importação do mesmo lote é recusada ou duplica (H1)"),
    ("R8 Alteração indevida: origem do extrato, exportados, lotes aceitos, auditoria, originais", "H1", "5",
     ["test_aut_int_01_travas_do_banco", "test_aut_int_01b_exportado_e_aceito_congelados",
      "test_aut_int_02_arquivo_adulterado"], "-"),
    ("R9 Perda de informação: ida e volta do arquivo, itens do lote, migração de banco antigo", "H1", "5",
     ["test_aut_int_03_ida_e_volta_detecta_diferenca", "test_aut_int_03b_falha_de_ida_e_volta_bloqueia_lote",
      "test_aut_mig_01_banco_antigo_e_migrado_sem_perder_dados"], "-"),
    ("R10 Leiaute conhecido preservado byte a byte", "H1", "Restrição",
     ["test_lote_fortes_completo_byte_a_byte", "test_validadores_bloqueantes"],
     "Aceitação do arquivo pelo Fortes (H1)"),
    ("R11 Nenhuma pendência é aprovada sem evidência verificável", "H1-H5", "8",
     ["test_aut_hom_01_h1_exige_lote_aceito_e_conferido", "test_aut_hom_01b_regras_gerais",
      "test_aut_hom_02_h4_aceita_so_relatorio_real_aprovado"], "-"),
    ("R12 Extratos reais do piloto carregam e fecham o saldo", "H5", "-",
     ["test_ofx_exemplo", "test_csv_com_mapeamento", "test_xlsx_entrada_saida"],
     "Carregar um OFX e um CSV/XLSX reais de cada banco (procedimento H5)"),
]


def rodar_pytest() -> dict[str, tuple[str, str]]:
    with tempfile.TemporaryDirectory() as t:
        xml = Path(t) / "r.xml"
        subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={xml}"], cwd=RAIZ,
                       capture_output=True, text=True)
        res: dict[str, tuple[str, str]] = {}
        for tc in ET.parse(xml).getroot().iter("testcase"):
            nome = f"{tc.get('classname', '').split('.')[-1]}::{tc.get('name')}"
            falha = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
            status = "FALHOU" if falha is not None else ("PULADO" if tc.find("skipped") is not None else "passou")
            res[nome] = (status, (falha.get("message") or "")[:200] if falha is not None else "")
        return res


def casar(res: dict, base: str) -> list[tuple[str, tuple[str, str]]]:
    return [(n, r) for n, r in res.items() if n.split("::")[1].split("[")[0] == base]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    ap.add_argument("--saida", type=Path, default=RAIZ.parent / "docs" / "conciliador-fortes" / "homologacao")
    a = ap.parse_args()
    a.saida.mkdir(parents=True, exist_ok=True)
    res = rodar_pytest()
    total, ok = len(res), sum(1 for s, _ in res.values() if s == "passou")
    falhas = [(n, m) for n, (s, m) in res.items() if s == "FALHOU"]
    agora = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

    # ---- matriz
    inexistentes, linhas = [], []
    for req, item, dir_, testes, real in MATRIZ:
        celulas = []
        for t in testes:
            achados = casar(res, t)
            if not achados:
                inexistentes.append(t)
                celulas.append(f"`{t}` (NÃO EXISTE)")
                continue
            ruins = [n for n, (s, _) in achados if s != "passou"]
            celulas.append(f"`{t}` {'×' + str(len(achados)) if len(achados) > 1 else ''} "
                           f"{'FALHOU' if ruins else 'passou'}")
        linhas.append(f"| {req} | {item} | {dir_} | {'<br>'.join(celulas)} | {real} |")
    (a.saida / "matriz-rastreabilidade.md").write_text(
        f"# Matriz de rastreabilidade (gerada em {agora})\n\n"
        "Gerada por `scripts/relatorio_homologacao.py`; não edite à mão. A coluna de testes mostra o resultado "
        "da execução real da suíte. A última coluna lista o que só a instalação real do Fortes comprova: "
        "**teste automatizado nunca aprova esses itens**.\n\n"
        "| Requisito | Item | Diretriz | Testes automatizados (resultado) | Só a instalação real comprova |\n"
        "|---|---|---|---|---|\n" + "\n".join(linhas) + "\n", encoding="utf-8")

    # ---- relatório
    central = conectar_central(a.data_dir) if (a.data_dir / "central.db").exists() else None
    est = hom.estado(central) if central else {k: None for k in hom.ITENS}
    sec = []
    for cod, item in hom.ITENS.items():
        r = est[cod]
        if r is None:
            sec.append(f"### {cod} · {item.titulo}\n\n- **Estado: NÃO TESTADO NA INSTALAÇÃO REAL.**\n"
                       f"- Critério de aprovação: {item.criterio}\n- Evidência: nenhuma registrada.\n"
                       f"- Procedimento: `instrucoes-escritorio.md`, seção {cod}.\n")
        else:
            integra = hom.evidencia_integra(r)
            sec.append(f"### {cod} · {item.titulo}\n\n- **Estado: {r['status'].upper()}** "
                       f"(registrado por {r['registrado_por']} em {r['registrado_em']})\n"
                       f"- Teste realizado: {r['teste']}\n- Resultado: {r['resultado']}\n"
                       f"- Evidência: {r['evidencia_nome'] or 'nenhuma'}"
                       f"{' · SHA-256 ' + r['evidencia_sha256'][:16] + '… · íntegra: ' + ('sim' if integra else 'NÃO') if r['evidencia_sha256'] else ''}\n"
                       f"- Falha identificada: {r['falha'] or '-'}\n- Ação corretiva: {r['acao_corretiva'] or '-'}\n")
    liberada = bool(central) and hom.integracao_liberada(central)
    cab = (f"# Relatório de homologação da P-004 (gerado em {agora})\n\n"
           f"**Integração com o Fortes: {'LIBERADA' if liberada else 'NÃO LIBERADA'}.** "
           f"Liberação exige H1 a H5 aprovados, cada um com evidência.\n\n"
           f"## 1. Testes automatizados (não dependem do Fortes)\n\n"
           f"- Executados: {total} · passaram: {ok} · falharam: {len(falhas)}\n"
           f"- Testes citados na matriz que não existem: {len(inexistentes)}"
           f"{' → ' + ', '.join(inexistentes) if inexistentes else ''}\n"
           f"- Escopo: leitura de arquivos, regras, validadores, travas do banco, duplicidade, integridade, "
           f"backup/restauração em pasta temporária. Usam só dados sintéticos.\n"
           f"- O que eles **não** provam: que o Fortes aceita o arquivo, o limite do histórico, o formato do "
           f"Razão real, o comportamento com extratos reais.\n")
    if falhas:
        cab += "\n### Falhas encontradas na execução\n\n" + "\n".join(f"- `{n}`: {m}" for n, m in falhas) + "\n"
    cab += ("\n## 2. Testes que dependem da instalação real do Fortes\n\n"
            "Estado lido dos registros de homologação (`central.db`). Item sem registro com evidência "
            "fica **não testado**.\n\n")
    rod = ("\n## 3. Falhas identificadas e ações corretivas (histórico da construção)\n\n"
           "| Falha | Como apareceu | Ação corretiva | Evidência |\n|---|---|---|---|\n"
           "| Registro de “lote bloqueado” sumia da auditoria (rollback junto com a operação) | teste de fluxo completo | "
           "registro feito em transação à parte | `test_lote_fortes_completo_byte_a_byte` |\n"
           "| Abas voltavam para a primeira após cada ação | teste de navegador | abas com estado preservado | "
           "`tests/e2e/fluxo_primeira_configuracao.js` |\n"
           "| Teste de duplicidade mal desenhado (não exercitava o bloqueio) | mutação: a proteção foi desligada e o teste seguiu passando | "
           "teste reescrito (`test_aut_dup_02_...`); nova mutação passou a ser detectada | mutação documentada no plano de testes |\n"
           "\nNenhuma falha do app foi observada na instalação real, porque nenhum teste nela foi executado.\n")
    (a.saida / "relatorio-homologacao.md").write_text(cab + "\n".join(sec) + rod, encoding="utf-8")
    print(f"{ok}/{total} testes passaram; matriz e relatório em {a.saida}")
    if inexistentes:
        sys.exit(f"testes da matriz que não existem: {inexistentes}")
    sys.exit(0 if not falhas else 1)


main()
