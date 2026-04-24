"""
WoW Character Scraper
=====================

Extrai do armory do personagem:
- Nivel de item (item level) de cada peca equipada + item_id
- Classificacao Mitica+ (rating numerico da temporada atual)
- Melhores corridas de Chave Mitica (nome da masmorra + numero da chave)

Uso interativo:
    python wow_character_scraper.py

Uso como modulo:
    from wow_character_scraper import fetch_character_data
    data = fetch_character_data(region="us", realm="stormrage", name="retribully")

Observacao tecnica:
    A pagina https://worldofwarcraft.blizzard.com/pt-br/character/<region>/<realm>/<name>
    e renderizada pelo Next.js e, hoje, responde 403 a scrapers sem fingerprint
    de browser. Alem disso o conteudo e hidratado via JS. Por isso o caminho
    primario aqui e a API publica da Raider.IO, que espelha os mesmos dados que
    aparecem no armory. Se a Blizzard servir o HTML, o script ainda tenta
    extrair o blob JSON embutido na tag <script id="__NEXT_DATA__">.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import requests

BLIZZARD_ARMORY_URL = (
    "https://worldofwarcraft.blizzard.com/pt-br/character/{region}/{realm}/{name}"
)
RAIDERIO_PROFILE_URL = "https://raider.io/api/v1/characters/profile"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


class CharacterNotFoundError(RuntimeError):
    pass


def _fetch_raiderio(region: str, realm: str, name: str) -> dict[str, Any]:
    params = {
        "region": region.lower(),
        "realm": realm.lower(),
        "name": name.lower(),
        "fields": ",".join(
            [
                "gear",
                "mythic_plus_scores_by_season:current",
                "mythic_plus_best_runs",
            ]
        ),
    }
    resp = requests.get(
        RAIDERIO_PROFILE_URL,
        params=params,
        headers={**BROWSER_HEADERS, "Accept": "application/json"},
        timeout=30,
    )
    if resp.status_code == 400:
        raise CharacterNotFoundError(
            f"Personagem nao encontrado: {name}@{realm}-{region}"
        )
    resp.raise_for_status()
    return resp.json()


def _fetch_blizzard_armory(region: str, realm: str, name: str) -> dict[str, Any] | None:
    """Tenta baixar o HTML do armory e extrair o __NEXT_DATA__ embutido."""
    url = BLIZZARD_ARMORY_URL.format(
        region=region.lower(), realm=realm.lower(), name=name.lower()
    )
    try:
        resp = requests.get(
            url,
            headers={
                **BROWSER_HEADERS,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _parse_equipment(gear: dict[str, Any]) -> list[dict[str, Any]]:
    items = (gear or {}).get("items") or {}
    parsed: list[dict[str, Any]] = []
    for slot, data in items.items():
        if not isinstance(data, dict):
            continue
        parsed.append(
            {
                "slot": slot,
                "item_id": data.get("item_id"),
                "item_level": data.get("item_level"),
                "name": data.get("name"),
                "quality": data.get("item_quality"),
                "icon": data.get("icon"),
            }
        )
    return parsed


def _parse_mythic_plus_rating(scores: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not scores:
        return None
    current = scores[0]
    inner = current.get("scores") or {}
    segments = current.get("segments") or {}
    all_segment = segments.get("all") if isinstance(segments, dict) else None
    return {
        "season": current.get("season"),
        "score": inner.get("all"),
        "score_color": (all_segment or {}).get("color"),
        "dps": inner.get("dps"),
        "healer": inner.get("healer"),
        "tank": inner.get("tank"),
    }


def _parse_best_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed = []
    for run in runs or []:
        parsed.append(
            {
                "dungeon": run.get("dungeon"),
                "short_name": run.get("short_name"),
                "keystone_level": run.get("mythic_level"),
                "num_keystone_upgrades": run.get("num_keystone_upgrades"),
                "score": run.get("score"),
                "clear_time_ms": run.get("clear_time_ms"),
                "par_time_ms": run.get("par_time_ms"),
                "completed_at": run.get("completed_at"),
                "url": run.get("url"),
            }
        )
    return parsed


def fetch_character_data(region: str, realm: str, name: str) -> dict[str, Any]:
    """Retorna um dicionario JSON-serializavel com o equipamento, rating M+
    e melhores chaves miticas do personagem informado.
    """
    raw = _fetch_raiderio(region, realm, name)

    gear = raw.get("gear") or {}
    return {
        "character": {
            "name": raw.get("name"),
            "realm": raw.get("realm"),
            "region": raw.get("region"),
            "class": raw.get("class"),
            "active_spec": raw.get("active_spec_name"),
            "race": raw.get("race"),
            "faction": raw.get("faction"),
            "profile_url": raw.get("profile_url"),
            "thumbnail_url": raw.get("thumbnail_url"),
        },
        "equipment": {
            "item_level_equipped": gear.get("item_level_equipped"),
            "item_level_total": gear.get("item_level_total"),
            "items": _parse_equipment(gear),
        },
        "mythic_plus_rating": _parse_mythic_plus_rating(
            raw.get("mythic_plus_scores_by_season") or []
        ),
        "mythic_plus_best_runs": _parse_best_runs(
            raw.get("mythic_plus_best_runs") or []
        ),
    }


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or (default or "")


def main() -> int:
    print("=== WoW Character Scraper ===")
    print("Informe os dados do personagem que aparecem na URL do armory:")
    print("  https://worldofwarcraft.blizzard.com/pt-br/character/<region>/<realm>/<name>\n")

    region = _prompt("Regiao (us, eu, kr, tw)", "us")
    realm = _prompt("Servidor (ex: stormrage)")
    name = _prompt("Nome do personagem (ex: retribully)")

    if not realm or not name:
        print("Erro: servidor e nome do personagem sao obrigatorios.", file=sys.stderr)
        return 1

    try:
        data = fetch_character_data(region=region, realm=realm, name=name)
    except CharacterNotFoundError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2
    except requests.HTTPError as e:
        print(f"Erro HTTP ao buscar personagem: {e}", file=sys.stderr)
        return 3
    except requests.RequestException as e:
        print(f"Erro de rede: {e}", file=sys.stderr)
        return 3

    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
