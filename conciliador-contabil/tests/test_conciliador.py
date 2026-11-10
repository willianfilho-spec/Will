"""Testes:  python -m unittest discover -s tests   (a partir de conciliador-contabil/)"""

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
from conciliador.pipeline import conciliar  # noqa: E402
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
        transacoes, saldos = ler_extrato(EXEMPLO)
        self.assertEqual(len(transacoes), 20)
        self.assertEqual(saldos, 1)
        self.assertEqual(sum(t.valor for t in transacoes), Decimal("-8108.68"))

    def test_colunas_debito_credito_virgula_latin1(self):
        caminho = self._gravar(
            "Data,Histórico,Débito,Crédito\n2026-10-01,TARIFA,\"10,00\",\n2026-10-02,PIX RECEBIDO,,\"25,50\"\n",
            codificacao="latin-1",
        )
        transacoes, _ = ler_extrato(caminho)
        self.assertEqual([t.valor for t in transacoes], [Decimal("-10.00"), Decimal("25.50")])

    def test_coluna_tipo(self):
        caminho = self._gravar("data;descricao;valor;tipo\n01/10/2026;TARIFA;10,00;D\n")
        transacoes, _ = ler_extrato(caminho)
        self.assertEqual(transacoes[0].valor, Decimal("-10.00"))

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

    def test_regra_com_conta_inexistente_e_rejeitada(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as arquivo:
            arquivo.write('{"conta_banco": "1.1.1.02", "conta_transitoria": "1.1.9.99", "regras": '
                          '[{"nome": "x", "palavras_chave": ["X"], "conta": "9.9.9.99"}]}')
        with self.assertRaises(ErroConfiguracao):
            carregar_configuracao(arquivo.name, PLANO)


class TesteFimAFim(unittest.TestCase):
    def test_linha_de_comando(self):
        with tempfile.TemporaryDirectory() as pasta:
            self.assertEqual(main([str(EXEMPLO), "--saida", pasta]), 0)
            linhas = (Path(pasta) / "lancamentos.csv").read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(len(linhas), 21)  # cabeçalho + 20 lançamentos
            revisao = (Path(pasta) / "revisao.csv").read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(len(revisao), 10)  # cabeçalho + 6 a revisar + 3 pendentes

    def test_arquivo_inexistente_retorna_erro(self):
        self.assertEqual(main(["nao_existe.csv"]), 1)


if __name__ == "__main__":
    unittest.main()
