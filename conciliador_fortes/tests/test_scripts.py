import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def rodar(*args):
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "validar_lote_existente.py"), *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


def test_scr_01_validador_de_lote_existente(tmp_path):
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"31/08/2026;362;90;1000,00;ABERTURA [AB-000001];;;;\r\n"
                    b"02/09/2026;259;362;45,90;TARIFA [NX-202609-00001];;;;\r\n"
                    b"02/09/2026;2;375;45,90;RECLASSIFICA [NX-202609-00001];;;;\r\n")
    code, out = rodar(bom, "--banco", "362", "--saldo", "2026-09-30=954,10")
    assert code == 0 and "BATE" in out and "1 aviso" in out and "NÃO é aceitação" in out  # marca repetida = aviso
    code, out = rodar(bom, "--banco", "362", "--saldo", "2026-09-30=1,00")
    assert code == 1 and "NÃO BATE" in out
    ruim = tmp_path / "ruim.csv"
    ruim.write_bytes(b"02/09/2026;259;259;10,00;MESMA CONTA;;;;\r\n02/09/2026;259;362;10,00;X;;;;\r\n02/09/2026;259;362;10,00;X;;;;\r\n"
                     b"32/09/2026;1;2;5,00;DATA RUIM;;;;\r\n02/09/2026;1;2;5,00\r\n")
    code, out = rodar(ruim)
    assert code == 1 and "débito igual a crédito" in out and "idêntica repetida" in out
    assert "campos" in out and "linha 4" in out
    semcrlf = tmp_path / "lf.csv"
    semcrlf.write_bytes(b"02/09/2026;259;362;10,00;X;;;;\n")
    assert rodar(semcrlf)[0] == 1
    plano = tmp_path / "plano.csv"
    plano.write_bytes(b'"1";"ATIVO";;;X;"Devedora"\n"1.1";"Banco";362;X;X;"Devedora"\n"2.1";"Desp";259;X;X;"Devedora"\n')
    ok = tmp_path / "ok.csv"
    ok.write_bytes(b"02/09/2026;259;362;10,00;X;;;;\r\n02/09/2026;999;362;10,00;Y;;;;\r\n")
    code, out = rodar(ok, "--plano", plano)
    assert code == 1 and "999" in out and "não existe no plano" in out
