"""
Simulador Integrado — junta o scraper do armory com o simulador estatistico.

Fluxo:
  1) Para cada personagem, pede regiao/servidor/nome
  2) Chama wow_character_scraper.fetch_character_data() para baixar o gear
  3) Conta itens Myth (item_level >= 272), calcula o progresso 1/6 a 6/6
     e usa isso como `k`, `crests` equivalentes e `maxxed`
  4) Executa "Simulador estatistico.py" via subprocess passando os args
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
import subprocess
import sys
from pathlib import Path
from typing import Any

from wow_character_scraper import CharacterNotFoundError, fetch_character_data

ROOT = Path(__file__).parent
SIMULADOR_PATH = ROOT / "Simulador estatistico.py"
SKIP_CHARACTER = object()

# Progressao Myth informada pelo usuario:
# 272=1/6, 276=2/6, 279=3/6, 282=4/6, 286=5/6, 289=6/6.
MYTH_BASE_ILVL_DEFAULT = 272
MYTH_PROGRESS_BY_ILVL = [
    (289, "6/6", 100),
    (286, "5/6", 80),
    (282, "4/6", 60),
    (279, "3/6", 40),
    (276, "2/6", 20),
    (272, "1/6", 0),
]
CRESTS_TO_MAX_MYTH_ITEM = 100
DEFAULT_WEEKS_REMAINING = 15
DEFAULT_TOTAL_ITEMS = 18

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
        "realm_required": "  ! servidor obrigatorio. Pulando este personagem.",
        "fetching": "  Buscando {name}@{realm}-{region}...",
        "fetch_ok": "  OK: ilvl medio={avg}, ilvl equipado(raider.io)={equipped}",
        "fetch_error": "  ! erro ao buscar: {err}",
        "myth_count": "  -> {k} item(ns) Myth detectado(s) (ilvl >= {th}):",
        "myth_item_line": "     - {slot:<10} ilvl {ilvl:>4}  {progress:<3}  crests {spent:>3}/{total:<3}  falta {missing:>3}  {name}",
        "rating_summary": "  M+ rating: {score}  |  {n} melhores corridas registradas",
        "no_chars": "Nenhum personagem coletado. Encerrando.",
        "summary_header": "{n} personagem(ns) coletado(s):",
        "summary_line": "  - {name}: k={k}, maxxed={maxxed}, crests equivalentes={crests}, faltam={missing}",
        "auto_config": "Configuracao automatica: semanas={weeks}, total de itens={total}",
        "running": "=== Executando simulador ===",
        "command": "$ {cmd}",
    },
    "en-us": {
        "lang_prompt": "Idioma do relatorio / Report language [1] pt-br  [2] en-us",
        "title": "=== Integrated Simulator (scraper + statistics) ===",
        "intro": "Add one or more characters. Empty ENTER on name finishes.",
        "char_header": "--- Character #{n} ---",
        "ask_name": "Character name (empty ENTER to finish)",
        "ask_region": "Server region (us, eu, kr, tw)",
        "ask_realm": "Realm (e.g. stormrage)",
        "realm_required": "  ! realm is required. Skipping this character.",
        "fetching": "  Fetching {name}@{realm}-{region}...",
        "fetch_ok": "  OK: avg ilvl={avg}, equipped ilvl(raider.io)={equipped}",
        "fetch_error": "  ! fetch error: {err}",
        "myth_count": "  -> {k} Myth item(s) detected (ilvl >= {th}):",
        "myth_item_line": "     - {slot:<10} ilvl {ilvl:>4}  {progress:<3}  crests {spent:>3}/{total:<3}  missing {missing:>3}  {name}",
        "rating_summary": "  M+ rating: {score}  |  {n} best runs recorded",
        "no_chars": "No characters collected. Exiting.",
        "summary_header": "{n} character(s) collected:",
        "summary_line": "  - {name}: k={k}, maxxed={maxxed}, equivalent crests={crests}, missing={missing}",
        "auto_config": "Automatic config: weeks={weeks}, total items={total}",
        "running": "=== Running simulator ===",
        "command": "$ {cmd}",
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
def myth_progress_for_ilvl(item_level: int) -> tuple[str, int] | None:
    """Retorna (progressao, crests_gastos) para um item Myth pelo item level."""
    for min_ilvl, progress, crests_spent in MYTH_PROGRESS_BY_ILVL:
        if item_level >= min_ilvl:
            return progress, crests_spent
    return None


def analyze_myth_items(scraped: dict[str, Any]) -> dict[str, Any]:
    """Calcula k, itens maxxed e crests equivalentes ja investidos."""
    items = scraped.get("equipment", {}).get("items") or []
    myth_items = []
    maxxed = 0
    equivalent_crests = 0

    for item in items:
        item_level = item.get("item_level")
        if not isinstance(item_level, int):
            continue
        progress = myth_progress_for_ilvl(item_level)
        if progress is None:
            continue

        progress_label, crests_spent = progress
        is_maxxed = crests_spent >= CRESTS_TO_MAX_MYTH_ITEM
        if is_maxxed:
            maxxed += 1
        else:
            equivalent_crests += crests_spent

        missing = max(0, CRESTS_TO_MAX_MYTH_ITEM - crests_spent)
        myth_items.append({
            **item,
            "progress": progress_label,
            "crests_spent": crests_spent,
            "crests_missing": missing,
        })

    k = len(myth_items)
    effective_crests = equivalent_crests + maxxed * CRESTS_TO_MAX_MYTH_ITEM
    return {
        "k": k,
        "maxxed": maxxed,
        "equivalent_crests": equivalent_crests,
        "effective_crests": effective_crests,
        "crests_missing": max(0, k * CRESTS_TO_MAX_MYTH_ITEM - effective_crests),
        "items": myth_items,
    }


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or (default or "")


def _resolve_language(cli_lang: str | None) -> str:
    if cli_lang:
        if cli_lang not in SUPPORTED_LANGS:
            print(f"unknown lang '{cli_lang}', falling back to {DEFAULT_LANG}", file=sys.stderr)
            return DEFAULT_LANG
        return cli_lang
    print(STRINGS[DEFAULT_LANG]["lang_prompt"])
    choice = _prompt("Opcao / Choice", "1")
    return "en-us" if choice.strip() == "2" else DEFAULT_LANG


def _collect_character(lang: str) -> dict[str, Any] | None | object:
    name = _prompt(t(lang, "ask_name"))
    if not name:
        return None
    region = _prompt(t(lang, "ask_region"), "us")
    realm = _prompt(t(lang, "ask_realm"))
    if not realm:
        print(t(lang, "realm_required"))
        return SKIP_CHARACTER

    print(t(lang, "fetching", name=name, realm=realm, region=region))
    try:
        scraped = fetch_character_data(region=region, realm=realm, name=name)
    except CharacterNotFoundError as e:
        print(f"  ! {e}")
        return SKIP_CHARACTER
    except Exception as e:
        print(t(lang, "fetch_error", err=e))
        return SKIP_CHARACTER

    avg = scraped["equipment"].get("item_level_average")
    equipped = scraped["equipment"].get("item_level_equipped")
    print(t(lang, "fetch_ok", avg=avg, equipped=equipped))

    myth_threshold = MYTH_BASE_ILVL_DEFAULT
    myth_progress = analyze_myth_items(scraped)
    k = myth_progress["k"]
    myth_items = myth_progress["items"]

    print(t(lang, "myth_count", k=k, th=myth_threshold))
    for it in myth_items:
        print(t(
            lang,
            "myth_item_line",
            slot=it["slot"],
            ilvl=it["item_level"],
            progress=it["progress"],
            spent=it["crests_spent"],
            total=CRESTS_TO_MAX_MYTH_ITEM,
            missing=it["crests_missing"],
            name=it.get("name"),
        ))

    rating = scraped.get("mythic_plus_rating") or {}
    runs = scraped.get("mythic_plus_best_runs") or []
    print(t(lang, "rating_summary", score=rating.get("score"), n=len(runs)))

    sim_name = (scraped["character"].get("name") or name).lower().replace(" ", "")
    return {
        "sim_name": sim_name,
        "display_name": scraped["character"].get("name") or name,
        "k": k,
        "maxxed": myth_progress["maxxed"],
        "crests": myth_progress["equivalent_crests"],
        "crests_missing": myth_progress["crests_missing"],
        "myth_threshold": myth_threshold,
        "scraped": scraped,
    }


def _build_simulator_args(
    chars: list[dict[str, Any]],
    weeks: int,
    total: int,
    json_output: bool,
    lang: str,
) -> list[str]:
    if not SIMULADOR_PATH.exists():
        raise FileNotFoundError(f"Could not find {SIMULADOR_PATH}")

    chars_str = ",".join(f"{c['sim_name']}:{c['k']}" for c in chars)
    maxxed_str = ",".join(f"{c['sim_name']}:{c['maxxed']}" for c in chars)
    crests_str = ",".join(f"{c['sim_name']}:{c['crests']}" for c in chars)

    args = [
        sys.executable,
        str(SIMULADOR_PATH),
        "--characters",
        chars_str,
        "--lang",
        lang,
        "--weeks",
        str(weeks),
    ]
    if any(c["maxxed"] for c in chars):
        args += ["--maxxed", maxxed_str]
    if any(c["crests"] for c in chars):
        args += ["--crests", crests_str]
    if total != DEFAULT_TOTAL_ITEMS:
        args += ["--total", str(total)]
    if json_output:
        args += ["--json"]
    return args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Integrated WoW armory + Great Vault simulator")
    parser.add_argument("--lang", choices=SUPPORTED_LANGS, default=None,
                        help="Language for prompts and report output")
    parser.add_argument("--weeks", type=int, default=DEFAULT_WEEKS_REMAINING,
                        help=f"weeks remaining used by the simulator (default: {DEFAULT_WEEKS_REMAINING})")
    parser.add_argument("--total", type=int, default=DEFAULT_TOTAL_ITEMS,
                        help=f"total unique items in the pool (default: {DEFAULT_TOTAL_ITEMS})")
    parser.add_argument("--json", action="store_true",
                        help="pass --json to the statistical simulator")
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
        if char is SKIP_CHARACTER:
            print()
            continue
        if not isinstance(char, dict):
            print()
            continue
        chars.append(char)
        print()

    if not chars:
        print(t(lang, "no_chars"), file=sys.stderr)
        return 1

    print()
    print(t(lang, "summary_header", n=len(chars)))
    for c in chars:
        print(t(
            lang,
            "summary_line",
            name=c["display_name"],
            k=c["k"],
            maxxed=c["maxxed"],
            crests=c["crests"],
            missing=c["crests_missing"],
        ))
    print()

    total = args.total
    max_k = max(c["k"] for c in chars)
    if total < max_k:
        print(f"total must be >= largest k ({max_k})", file=sys.stderr)
        return 1
    if args.weeks < 1:
        print("weeks must be >= 1", file=sys.stderr)
        return 1

    print(t(lang, "auto_config", weeks=args.weeks, total=total))

    sim_args = _build_simulator_args(chars, args.weeks, total, args.json, lang)

    print()
    print(t(lang, "running"))
    print(t(lang, "command", cmd=" ".join(sim_args)))
    print()
    rc = subprocess.run(sim_args).returncode

    return rc


if __name__ == "__main__":
    sys.exit(main())
