"""
Simulador Integrado — junta o scraper do armory com o simulador estatistico.

Fluxo:
  1) Para cada personagem, pede regiao/servidor/nome
  2) Chama wow_character_scraper.fetch_character_data() para baixar o gear
  3) Conta itens Myth (item_level >= MYTH_BASE_ILVL) e usa esse numero como
     o `k` que o Simulador estatistico.py espera receber
  4) Pergunta data do fim da season (ou semanas restantes) e crests/maxxed
     opcionais por char
  5) Executa "Simulador estatistico.py" via subprocess passando os args
     montados a partir dos dados scrapeados

Uso:
    python simulador_integrado.py

Nao modifica nem o scraper nem o simulador — so amarra os dois.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from wow_character_scraper import CharacterNotFoundError, fetch_character_data

ROOT = Path(__file__).parent
SIMULADOR_PATH = ROOT / "Simulador estatistico.py"

# Item level base de uma peca Myth 1/6 (per README: "1/6 com item level 272").
# Itens equipados com ilvl >= esse valor sao contados como Myth.
MYTH_BASE_ILVL_DEFAULT = 272


def count_myth_items(scraped: dict[str, Any], myth_threshold: int) -> tuple[int, list[dict[str, Any]]]:
    """Retorna (k, lista de itens classificados como Myth) baseado no ilvl."""
    items = scraped.get("equipment", {}).get("items") or []
    myth_items = [
        i for i in items if isinstance(i.get("item_level"), int) and i["item_level"] >= myth_threshold
    ]
    return len(myth_items), myth_items


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or (default or "")


def _prompt_int(label: str, default: int) -> int:
    while True:
        raw = _prompt(label, str(default))
        try:
            return int(raw)
        except ValueError:
            print("  ! valor invalido, informe um numero inteiro.")


def _collect_character() -> dict[str, Any] | None:
    """Coleta dados de UM personagem via scraper. Retorna None se cancelado."""
    name = _prompt("Nome do personagem (ENTER vazio para encerrar)")
    if not name:
        return None
    region = _prompt("Regiao (us, eu, kr, tw)", "us")
    realm = _prompt("Servidor (ex: stormrage)")
    if not realm:
        print("  ! servidor obrigatorio. Pulando.")
        return None

    print(f"  Buscando {name}@{realm}-{region}...")
    try:
        scraped = fetch_character_data(region=region, realm=realm, name=name)
    except CharacterNotFoundError as e:
        print(f"  ! {e}")
        return None
    except Exception as e:
        print(f"  ! erro ao buscar: {e}")
        return None

    avg = scraped["equipment"].get("item_level_average")
    equipped = scraped["equipment"].get("item_level_equipped")
    print(f"  OK: ilvl medio={avg}, ilvl equipado(raider.io)={equipped}")

    myth_threshold = _prompt_int("Item level minimo Myth 1/6", MYTH_BASE_ILVL_DEFAULT)
    k, myth_items = count_myth_items(scraped, myth_threshold)

    print(f"  -> {k} item(ns) Myth detectado(s) (ilvl >= {myth_threshold}):")
    for it in myth_items:
        print(f"     - {it['slot']:<10} ilvl {it['item_level']:>4}  {it.get('name')}")

    override = _prompt(f"Sobrescrever k? (ENTER=manter {k})", "")
    if override:
        try:
            k = int(override)
        except ValueError:
            print(f"  ! valor invalido, mantendo k={k}")

    maxxed = _prompt_int(f"Quantos desses {k} ja em 6/6", 0)
    crests = _prompt_int("Crests Myth livres", 0)

    rating = scraped.get("mythic_plus_rating") or {}
    runs = scraped.get("mythic_plus_best_runs") or []
    print(f"  M+ rating: {rating.get('score')}  |  {len(runs)} melhores corridas registradas")

    sim_name = scraped["character"].get("name") or name
    sim_name = sim_name.lower().replace(" ", "")

    return {
        "sim_name": sim_name,
        "display_name": scraped["character"].get("name") or name,
        "k": k,
        "maxxed": maxxed,
        "crests": crests,
        "myth_threshold": myth_threshold,
        "scraped": scraped,
    }


def _build_simulator_args(
    chars: list[dict[str, Any]],
    season_end: str | None,
    weeks: int | None,
    total: int,
    json_output: bool,
) -> list[str]:
    if not SIMULADOR_PATH.exists():
        raise FileNotFoundError(f"Nao achei {SIMULADOR_PATH}")

    chars_str = ",".join(f"{c['sim_name']}:{c['k']}" for c in chars)
    maxxed_str = ",".join(f"{c['sim_name']}:{c['maxxed']}" for c in chars)
    crests_str = ",".join(f"{c['sim_name']}:{c['crests']}" for c in chars)

    args = [sys.executable, str(SIMULADOR_PATH), "--characters", chars_str]
    if season_end:
        args += ["--season-end", season_end]
    elif weeks is not None:
        args += ["--weeks", str(weeks)]
    if any(c["maxxed"] for c in chars):
        args += ["--maxxed", maxxed_str]
    if any(c["crests"] for c in chars):
        args += ["--crests", crests_str]
    if total != 18:
        args += ["--total", str(total)]
    if json_output:
        args += ["--json"]
    return args


def main() -> int:
    print("=== Simulador Integrado (scraper + estatistica) ===\n")

    chars: list[dict[str, Any]] = []
    print("Adicione um ou mais personagens. ENTER vazio no nome encerra.\n")
    while True:
        idx = len(chars) + 1
        print(f"--- Personagem #{idx} ---")
        char = _collect_character()
        if char is None:
            break
        chars.append(char)
        print()

    if not chars:
        print("Nenhum personagem coletado. Encerrando.", file=sys.stderr)
        return 1

    print(f"\n{len(chars)} personagem(ns) coletado(s):")
    for c in chars:
        print(f"  - {c['display_name']}: k={c['k']}, maxxed={c['maxxed']}, crests={c['crests']}")
    print()

    print("Tempo restante de season:")
    print("  [1] Informar a DATA do fim (DD/MM/YYYY)")
    print("  [2] Informar o NUMERO de semanas restantes")
    choice = _prompt("Opcao", "1")

    season_end: str | None = None
    weeks: int | None = None
    if choice == "2":
        weeks = _prompt_int("Semanas restantes", 15)
    else:
        season_end = _prompt("Data do fim da season (DD/MM/YYYY)")
        if not season_end:
            print("Data nao informada. Encerrando.", file=sys.stderr)
            return 1

    total = _prompt_int("Total de itens unicos no pool", 18)
    json_output = _prompt("Saida do simulador em JSON? (s/N)", "n").lower().startswith("s")

    args = _build_simulator_args(chars, season_end, weeks, total, json_output)

    print("\n=== Executando simulador ===")
    print(f"$ {' '.join(args)}\n")
    result = subprocess.run(args)

    if json_output:
        print("\n=== Dados brutos do scraper (por personagem) ===")
        snapshot = {
            c["display_name"]: {
                "k_myth": c["k"],
                "maxxed": c["maxxed"],
                "crests": c["crests"],
                "myth_threshold": c["myth_threshold"],
                "scraper": c["scraped"],
            }
            for c in chars
        }
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
