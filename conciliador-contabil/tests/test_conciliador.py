"""Testes:  python -m unittest discover -s tests   (a partir de conciliador-contabil/)"""

import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from conciliador.__main__ import main  # noqa: E402
from conciliador.leitor import ErroExtrato, converter_valor, ler_extrato  # noqa: E402
from conciliador.modelos import Transacao  # noqa: E402
from conciliador.modelos import Extrato  # noqa: E402
from conciliador.pipeline import ErroIntegridade, conciliar, conferir_saldo  # noqa: E402
from conciliador.regras import ErroConfiguracao, carregar_configuracao  # noqa: E402

REGRAS = RAIZ / "config" / "regras.json"
PLANO = RAIZ / "config" / "plano_de_contas.csv"
EXEMPLO = RAIZ / "exemplos" / "extrato_exemplo.csv"


def transacao(descricao, valor, linha=2):
    return Transacao(linha, date(2026, 10, 1), descricao, Decimal(valor))


class TesteValores(unittest.TestCase):
    def test_formatos(self):
        casos = {
            "1.234,56": "1234.56", "-1.234,56": "-1234.56", "1234.56": "1234.56",
            "1,234.56": "1234.56", "R$ 89,90": "89.90", "(50,00)": "-50.00",
            "50,00 D": "-50.00", "50,00 C": "50.00", "1.234": "1234", "12.5": "12.5",
        }
        for texto, esperado in casos.items():
            self.assertEqual(converter_valor(texto), Decimal(esperado), texto)

    def test_valor_invalido(self):
        with self.assertRaises(ValueError):
            converter_valor("abc")


class TesteLeitor(unittest.TestCase):
    def _gravar(self, conteudo, codificacao="utf-8"):
        arquivo = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding=codificacao)
        arquivo.write(conteudo)
        arquivo.close()
        return arquivo.name

    def test_exemplo(self):
        extrato = ler_extrato(EXEMPLO)
        self.assertEqual(len(extrato.transacoes), 22)
        self.assertEqual(extrato.linhas_saldo, 2)
        self.assertEqual((extrato.saldo_inicial, extrato.saldo_final), (Decimal("15000.00"), Decimal("6071.32")))
        self.assertEqual(sum(t.valor for t in extrato.transacoes), Decimal("-8928.68"))

    def test_colunas_debito_credito_virgula_latin1(self):
        caminho = self._gravar(
            "Data,Histórico,Débito,Crédito\n2026-10-01,TARIFA,\"10,00\",\n2026-10-02,PIX RECEBIDO,,\"25,50\"\n",
            codificacao="latin-1",
        )
        transacoes = ler_extrato(caminho).transacoes
        self.assertEqual([t.valor for t in transacoes], [Decimal("-10.00"), Decimal("25.50")])

    def test_coluna_tipo(self):
        caminho = self._gravar("data;descricao;valor;tipo\n01/10/2026;TARIFA;10,00;D\n")
        transacoes = ler_extrato(caminho).transacoes
        self.assertEqual(transacoes[0].valor, Decimal("-10.00"))

    def test_cabecalho_depois_de_linhas_de_titulo(self):
        caminho = self._gravar("Banco Exemplo S.A.\nAgência 0001 Conta 12345-6\n\ndata;descricao;valor\n01/10/2026;TARIFA;-10,00\n")
        transacoes = ler_extrato(caminho).transacoes
        self.assertEqual((transacoes[0].linha, transacoes[0].valor), (5, Decimal("-10.00")))

    def test_xlsx(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl não instalado")
        from datetime import datetime
        pasta = tempfile.mkdtemp()
        livro = openpyxl.Workbook()
        aba = livro.active
        aba.append(["Extrato de conta corrente"])
        aba.append(["Data", "Histórico", "Débito", "Crédito"])
        aba.append([datetime(2026, 10, 1), "SALDO ANTERIOR", None, 100.0])
        aba.append([datetime(2026, 10, 2), "TARIFA PACOTE", 35.5, None])
        aba.append(["03/10/2026", "PIX RECEBIDO FULANO", 0, "1.200,00"])
        livro.save(f"{pasta}/extrato.xlsx")
        extrato = ler_extrato(f"{pasta}/extrato.xlsx")
        self.assertEqual([t.valor for t in extrato.transacoes], [Decimal("-35.50"), Decimal("1200.00")])
        self.assertEqual(extrato.transacoes[0].data, date(2026, 10, 2))
        self.assertEqual(extrato.saldo_inicial, Decimal("100.00"))

    def test_formato_nao_suportado(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as arquivo, self.assertRaises(ErroExtrato):
            ler_extrato(arquivo.name)

    def test_linha_invalida_interrompe(self):
        caminho = self._gravar("data;descricao;valor\n01/10/2026;TARIFA;10,00\n32/10/2026;X;abc\n")
        with self.assertRaises(ErroExtrato) as contexto:
            ler_extrato(caminho)
        self.assertIn("linha 3", str(contexto.exception))


class TesteClassificacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = carregar_configuracao(REGRAS, PLANO)

    def um(self, descricao, valor, sugestoes=None):
        return conciliar([transacao(descricao, valor)], self.config, sugestoes)[0]

    def test_saida_debita_despesa_credita_banco(self):
        l = self.um("Débito automático Energisa", "-412.37")
        self.assertEqual((l.conta_debito, l.conta_credito), ("4.1.1.01", "1.1.1.02"))
        self.assertEqual((l.valor, l.status), (Decimal("412.37"), "CLASSIFICADO"))

    def test_entrada_debita_banco(self):
        l = self.um("RENDIMENTO APLIC FINANCEIRA", "41.87")
        self.assertEqual((l.conta_debito, l.conta_credito), ("1.1.1.02", "3.2.1.01"))

    def test_sentido_da_regra_e_respeitado(self):
        # "RESGATE" só vale para entradas; numa saída não pode classificar.
        self.assertEqual(self.um("RESGATE", "-100").status, "PENDENTE")

    def test_palavra_inteira(self):
        # "TIM" não pode casar dentro de "ULTIMO"; "IOF" não casa em "BIOFARMA".
        self.assertEqual(self.um("ULTIMO PAGAMENTO BIOFARMA", "-100").status, "PENDENTE")

    def test_sem_regra_vai_para_transitoria(self):
        l = self.um("COMPRA POSTO SAO JORGE", "-250")
        self.assertEqual((l.conta_debito, l.origem, l.status), ("1.1.9.99", "PENDENTE", "PENDENTE"))

    def test_regra_generica_pede_revisao(self):
        self.assertEqual(self.um("PIX RECEBIDO - FULANO", "100").status, "REVISAR")

    def test_conflito_entre_regras_pede_revisao(self):
        l = self.um("JUROS MULTA BOLETO ATRASO VIVO", "-12.40")
        self.assertEqual(l.status, "REVISAR")
        self.assertIn("Conflito", l.observacao)

    def test_duplicidade_e_sinalizada_sem_descartar(self):
        iguais = [transacao("TARIFA", "-10", 2), transacao("TARIFA", "-10", 3)]
        lancamentos = conciliar(iguais, self.config)
        self.assertEqual(len(lancamentos), 2)
        self.assertTrue(all("duplicidade" in l.observacao for l in lancamentos))

    def test_sugestao_da_ia_sempre_para_revisao_e_regra_tem_prioridade(self):
        sugestao = {2: {"conta": "4.1.1.04", "confianca": "alta", "justificativa": "teste"}}
        l = self.um("COMPRA POSTO SAO JORGE", "-250", sugestao)
        self.assertEqual((l.conta_debito, l.origem, l.status), ("4.1.1.04", "IA", "REVISAR"))
        self.assertEqual(self.um("TARIFA", "-10", sugestao).origem, "REGRA")

    def test_saldo(self):
        extrato = Extrato([transacao("A", "100"), transacao("B", "-30", 3)], Decimal("50"), Decimal("120"))
        self.assertTrue(conferir_saldo(extrato).startswith("CONFERE"))
        extrato.saldo_final = Decimal("125")
        with self.assertRaises(ErroIntegridade):
            conferir_saldo(extrato)
        self.assertTrue(conferir_saldo(extrato, saldo_final=Decimal("120")).startswith("CONFERE"))
        extrato.saldo_inicial = None
        self.assertTrue(conferir_saldo(extrato).startswith("NÃO CONFERIDO"))

    def test_fornecedor_com_apelidos_equivalentes(self):
        for descricao in ("PIX ENVIADO NX COMERCIO", "PIX F. OLAVO", "TED F OLAVO LTDA", "pix f.olavo"):
            l = self.um(descricao, "-500")
            self.assertEqual((l.fornecedor, l.conta_debito, l.status),
                             ("NX / F. Olavo", "2.1.1.01", "CLASSIFICADO"), descricao)
        # "NX" só casa como palavra inteira, e só em saídas.
        self.assertEqual(self.um("PIX ENVIADO ANXIETY STORE", "-500").fornecedor, "")
        self.assertEqual(self.um("PIX RECEBIDO NX", "500").fornecedor, "")

    def test_duplicidade_com_regra_especifica_pede_revisao(self):
        iguais = [transacao("TARIFA", "-10", 2), transacao("TARIFA", "-10", 3)]
        self.assertEqual({l.status for l in conciliar(iguais, self.config)}, {"REVISAR"})

    def test_regra_com_conta_inexistente_e_rejeitada(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as arquivo:
            arquivo.write('{"conta_banco": "1.1.1.02", "conta_transitoria": "1.1.9.99", "regras": '
                          '[{"nome": "x", "palavras_chave": ["X"], "conta": "9.9.9.99"}]}')
        with self.assertRaises(ErroConfiguracao):
            carregar_configuracao(arquivo.name, PLANO)


class TesteFimAFim(unittest.TestCase):
    def _ler(self, caminho):
        with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
            return list(csv.DictReader(arquivo, delimiter=";"))

    def _gravar(self, caminho, linhas):
        with open(caminho, "w", encoding="cp1252", newline="") as arquivo:  # como o Excel salvaria
            escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]), delimiter=";")
            escritor.writeheader()
            escritor.writerows(linhas)

    def test_ciclo_completo_de_revisao(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            revisao, importacao = pasta / "revisao.csv", pasta / "importacao.csv"

            # 1a rodada: há pendências, então o arquivo de importação não é gerado.
            self.assertEqual(main([str(EXEMPLO), "--saida", str(pasta)]), 0)
            self.assertEqual(len(self._ler(pasta / "lancamentos.csv")), 22)
            linhas = self._ler(revisao)
            self.assertEqual(len(linhas), 9)
            self.assertFalse(importacao.exists())

            # Aprovação com conta inexistente é recusada e nada é sobrescrito.
            ruins = [dict(l, status="APROVADO", conta_debito="9.9.9.99") if l["status"] == "PENDENTE"
                     and l["conta_credito"] == "1.1.1.02" else dict(l) for l in linhas]
            self._gravar(revisao, ruins)
            self.assertEqual(main([str(EXEMPLO), "--saida", str(pasta), "--revisao", str(revisao)]), 1)
            # Rodar sem --revisao perderia as aprovações: também é recusado.
            self.assertEqual(main([str(EXEMPLO), "--saida", str(pasta)]), 1)

            # Aprovação válida de tudo: pendentes ganham contrapartida definitiva.
            boas = []
            for l in linhas:
                l = dict(l, status="APROVADO")
                if l["conta_debito"] == "1.1.9.99":
                    l["conta_debito"] = "4.1.2.01"
                if l["conta_credito"] == "1.1.9.99":
                    l["conta_credito"] = "1.1.2.01"
                boas.append(l)
            self._gravar(revisao, boas)
            self.assertEqual(main([str(EXEMPLO), "--saida", str(pasta), "--revisao", str(revisao)]), 0)

            finais = self._ler(pasta / "lancamentos.csv")
            self.assertEqual({l["status"] for l in finais}, {"CLASSIFICADO", "APROVADO"})
            self.assertEqual(sum(l["origem"] == "MANUAL" for l in finais), 3)
            self.assertEqual(len(self._ler(revisao)), 9)  # as decisões ficam registradas
            self.assertEqual(len(importacao.read_text(encoding="utf-8").splitlines()), 23)

            registros = [json.loads(l) for l in (pasta / "auditoria.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(registros), 2)  # só as rodadas concluídas
            self.assertEqual(len(registros[-1]["aprovacoes_e_alteracoes_manuais"]), 9)
            self.assertIsNotNone(registros[-1]["arquivo_de_importacao"])

    def test_saldo_divergente_interrompe(self):
        with tempfile.TemporaryDirectory() as pasta:
            self.assertEqual(main([str(EXEMPLO), "--saida", pasta, "--saldo-final", "6.000,00"]), 1)
            self.assertFalse((Path(pasta) / "lancamentos.csv").exists())

    def test_arquivo_inexistente_retorna_erro(self):
        self.assertEqual(main(["nao_existe.csv"]), 1)


if __name__ == "__main__":
    unittest.main()
