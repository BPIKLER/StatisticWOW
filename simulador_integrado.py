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

Idioma da interface e do relatorio: pt-br (default) ou en-us via --lang.
A regiao do servidor (us/eu/kr/tw) e independente do idioma — um char em
"us/stormrage" pode ser visualizado em pt-br ou en-us sem alterar a URL
do scraper.

Uso:
    python simulador_integrado.py
    python simulador_integrado.py --lang en-us

Nao modifica nem o scraper nem o simulador — so amarra os dois.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from wow_character_scraper import CharacterNotFoundError, fetch_character_data

ROOT = Path(__file__).parent
SIMULADOR_PATH = ROOT / "Simulador estatistico.py"

# Item level base de uma peca Myth 1/6 (per README: "1/6 com item level 272").
MYTH_BASE_ILVL_DEFAULT = 272

SUPPORTED_LANGS = ("pt-br", "en-us")
DEFAULT_LANG = "pt-br"


# ---------------------------------------------------------------------------
# i18n da interface do orquestrador (textos "frontend")
# ---------------------------------------------------------------------------
STRINGS: dict[str, dict[str, str]] = {
    "pt-br": {
        "lang_prompt": "Idioma do relatorio / Report language [1] pt-br  [2] en-us",
        "title": "=== Simulador Integrado (scraper + estatistica) ===",
        "intro": "Adicione um ou mais personagens. ENTER vazio no nome encerra.",
        "char_header": "--- Personagem #{n} ---",
        "ask_name": "Nome do personagem (ENTER vazio para encerrar)",
        "ask_region": "Regiao do servidor (us, eu, kr, tw)",
        "ask_realm": "Servidor (ex: stormrage)",
        "realm_required": "  ! servidor obrigatorio. Pulando.",
        "fetching": "  Buscando {name}@{realm}-{region}...",
        "fetch_ok": "  OK: ilvl medio={avg}, ilvl equipado(raider.io)={equipped}",
        "fetch_error": "  ! erro ao buscar: {err}",
        "ask_threshold": "Item level minimo Myth 1/6",
        "myth_count": "  -> {k} item(ns) Myth detectado(s) (ilvl >= {th}):",
        "ask_override_k": "Sobrescrever k? (ENTER=manter {k})",
        "invalid_int": "  ! valor invalido, mantendo k={k}",
        "ask_maxxed": "Quantos desses {k} ja em 6/6",
        "ask_crests": "Crests Myth livres",
        "rating_summary": "  M+ rating: {score}  |  {n} melhores corridas registradas",
        "no_chars": "Nenhum personagem coletado. Encerrando.",
        "summary_header": "{n} personagem(ns) coletado(s):",
        "summary_line": "  - {name}: k={k}, maxxed={maxxed}, crests={crests}",
        "season_header": "Tempo restante de season:",
        "season_opt1": "  [1] Informar a DATA do fim (DD/MM/YYYY)",
        "season_opt2": "  [2] Informar o NUMERO de semanas restantes",
        "season_choice": "Opcao",
        "ask_weeks": "Semanas restantes",
        "ask_season_end": "Data do fim da season (DD/MM/YYYY)",
        "no_date": "Data nao informada. Encerrando.",
        "ask_total": "Total de itens unicos no pool",
        "ask_json": "Saida do simulador em JSON? (s/N)",
        "running": "=== Executando simulador ===",
        "command": "$ {cmd}",
        "snapshot_header": "=== Dados brutos do scraper (por personagem) ===",
        "yes_token": "s",
        "default_yn": "s/N",
    },
    "en-us": {
        "lang_prompt": "Idioma do relatorio / Report language [1] pt-br  [2] en-us",
        "title": "=== Integrated Simulator (scraper + statistics) ===",
        "intro": "Add one or more characters. Empty ENTER on name finishes.",
        "char_header": "--- Character #{n} ---",
        "ask_name": "Character name (empty ENTER to finish)",
        "ask_region": "Server region (us, eu, kr, tw)",
        "ask_realm": "Realm (e.g. stormrage)",
        "realm_required": "  ! realm is required. Skipping.",
        "fetching": "  Fetching {name}@{realm}-{region}...",
        "fetch_ok": "  OK: avg ilvl={avg}, equipped ilvl(raider.io)={equipped}",
        "fetch_error": "  ! fetch error: {err}",
        "ask_threshold": "Minimum item level for Myth 1/6",
        "myth_count": "  -> {k} Myth item(s) detected (ilvl >= {th}):",
        "ask_override_k": "Override k? (ENTER=keep {k})",
        "invalid_int": "  ! invalid value, keeping k={k}",
        "ask_maxxed": "How many of these {k} are already at 6/6",
        "ask_crests": "Free Myth crests",
        "rating_summary": "  M+ rating: {score}  |  {n} best runs recorded",
        "no_chars": "No characters collected. Exiting.",
        "summary_header": "{n} character(s) collected:",
        "summary_line": "  - {name}: k={k}, maxxed={maxxed}, crests={crests}",
        "season_header": "Time left in season:",
        "season_opt1": "  [1] Provide season END DATE (DD/MM/YYYY)",
        "season_opt2": "  [2] Provide NUMBER of weeks remaining",
        "season_choice": "Choice",
        "ask_weeks": "Weeks remaining",
        "ask_season_end": "Season end date (DD/MM/YYYY)",
        "no_date": "No date provided. Exiting.",
        "ask_total": "Total unique items in the pool",
        "ask_json": "Simulator output as JSON? (y/N)",
        "running": "=== Running simulator ===",
        "command": "$ {cmd}",
        "snapshot_header": "=== Raw scraper data (per character) ===",
        "yes_token": "y",
        "default_yn": "y/N",
    },
}


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Retorna a string localizada (formatada com kwargs)."""
    table = STRINGS.get(lang, STRINGS[DEFAULT_LANG])
    template = table.get(key) or STRINGS[DEFAULT_LANG].get(key) or key
    return template.format(**kwargs) if kwargs else template


# ---------------------------------------------------------------------------
# Logica de negocio
# ---------------------------------------------------------------------------
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
            print("  ! invalid number / numero invalido")


def _resolve_language(cli_lang: str | None) -> str:
    if cli_lang:
        if cli_lang not in SUPPORTED_LANGS:
            print(f"unknown lang '{cli_lang}', falling back to {DEFAULT_LANG}", file=sys.stderr)
            return DEFAULT_LANG
        return cli_lang
    print(STRINGS[DEFAULT_LANG]["lang_prompt"])
    choice = _prompt("Opcao / Choice", "1")
    return "en-us" if choice.strip() == "2" else "pt-br"


def _collect_character(lang: str) -> dict[str, Any] | None:
    name = _prompt(t(lang, "ask_name"))
    if not name:
        return None
    region = _prompt(t(lang, "ask_region"), "us")
    realm = _prompt(t(lang, "ask_realm"))
    if not realm:
        print(t(lang, "realm_required"))
        return None

    print(t(lang, "fetching", name=name, realm=realm, region=region))
    try:
        scraped = fetch_character_data(region=region, realm=realm, name=name)
    except CharacterNotFoundError as e:
        print(f"  ! {e}")
        return None
    except Exception as e:
        print(t(lang, "fetch_error", err=e))
        return None

    avg = scraped["equipment"].get("item_level_average")
    equipped = scraped["equipment"].get("item_level_equipped")
    print(t(lang, "fetch_ok", avg=avg, equipped=equipped))

    myth_threshold = _prompt_int(t(lang, "ask_threshold"), MYTH_BASE_ILVL_DEFAULT)
    k, myth_items = count_myth_items(scraped, myth_threshold)

    print(t(lang, "myth_count", k=k, th=myth_threshold))
    for it in myth_items:
        print(f"     - {it['slot']:<10} ilvl {it['item_level']:>4}  {it.get('name')}")

    override = _prompt(t(lang, "ask_override_k", k=k), "")
    if override:
        try:
            k = int(override)
        except ValueError:
            print(t(lang, "invalid_int", k=k))

    maxxed = _prompt_int(t(lang, "ask_maxxed", k=k), 0)
    crests = _prompt_int(t(lang, "ask_crests"), 0)

    rating = scraped.get("mythic_plus_rating") or {}
    runs = scraped.get("mythic_plus_best_runs") or []
    print(t(lang, "rating_summary", score=rating.get("score"), n=len(runs)))

    sim_name = (scraped["character"].get("name") or name).lower().replace(" ", "")
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
    lang: str,
) -> list[str]:
    if not SIMULADOR_PATH.exists():
        raise FileNotFoundError(f"Could not find {SIMULADOR_PATH}")

    chars_str = ",".join(f"{c['sim_name']}:{c['k']}" for c in chars)
    maxxed_str = ",".join(f"{c['sim_name']}:{c['maxxed']}" for c in chars)
    crests_str = ",".join(f"{c['sim_name']}:{c['crests']}" for c in chars)

    args = [sys.executable, str(SIMULADOR_PATH), "--characters", chars_str, "--lang", lang]
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Integrated WoW armory + Great Vault simulator")
    parser.add_argument("--lang", choices=SUPPORTED_LANGS, default=None,
                        help="Language for prompts and report output")
    args = parser.parse_args(argv)

    lang = _resolve_language(args.lang)

    print()
    print(t(lang, "title"))
    print()
    print(t(lang, "intro"))
    print()

    chars: list[dict[str, Any]] = []
    while True:
        print(t(lang, "char_header", n=len(chars) + 1))
        char = _collect_character(lang)
        if char is None:
            break
        chars.append(char)
        print()

    if not chars:
        print(t(lang, "no_chars"), file=sys.stderr)
        return 1

    print()
    print(t(lang, "summary_header", n=len(chars)))
    for c in chars:
        print(t(lang, "summary_line",
                name=c["display_name"], k=c["k"], maxxed=c["maxxed"], crests=c["crests"]))
    print()

    print(t(lang, "season_header"))
    print(t(lang, "season_opt1"))
    print(t(lang, "season_opt2"))
    choice = _prompt(t(lang, "season_choice"), "1")

    season_end: str | None = None
    weeks: int | None = None
    if choice == "2":
        weeks = _prompt_int(t(lang, "ask_weeks"), 15)
    else:
        season_end = _prompt(t(lang, "ask_season_end"))
        if not season_end:
            print(t(lang, "no_date"), file=sys.stderr)
            return 1

    total = _prompt_int(t(lang, "ask_total"), 18)
    yes_token = STRINGS[lang]["yes_token"]
    json_answer = _prompt(t(lang, "ask_json"), "n").lower()
    json_output = json_answer.startswith(yes_token)

    sim_args = _build_simulator_args(chars, season_end, weeks, total, json_output, lang)

    print()
    print(t(lang, "running"))
    print(t(lang, "command", cmd=" ".join(sim_args)))
    print()
    rc = subprocess.run(sim_args).returncode

    if json_output:
        print()
        print(t(lang, "snapshot_header"))
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

    return rc


if __name__ == "__main__":
    sys.exit(main())
