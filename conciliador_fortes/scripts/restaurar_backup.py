"""Restaura um backup verificado numa pasta de dados nova.

    python scripts/restaurar_backup.py <pasta-do-backup> <nova-pasta-de-dados>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.backup import restaurar_backup, verificar_backup  # noqa: E402

if len(sys.argv) != 3:
    sys.exit(__doc__)
origem, destino = Path(sys.argv[1]), Path(sys.argv[2])
problemas = verificar_backup(origem)
if problemas:
    sys.exit("Backup com problema:\n- " + "\n- ".join(problemas))
restaurar_backup(origem, destino)
print(f"Restaurado em {destino}. Inicie com CONCILIADOR_DATA_DIR={destino} streamlit run app.py")
