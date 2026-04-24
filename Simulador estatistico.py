#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulador Monte Carlo + Programacao Dinamica
The Great Vault (World of Warcraft) - estrategia otima de coleta semanal

REGRA CRITICA DO JOGO:
    A cada semana, com s slots desbloqueados, voce ve s itens sorteados (com
    reposicao) entre os totais possiveis. Voce ESCOLHE NO MAXIMO 1. Logo,
    ganhar item novo eh evento bernoulli com p = 1 - (k/total)^s.
    O processo eh uma CADEIA DE MARKOV em k.

REGRA HARD-CODED:
    - Reset da vault eh sempre toca-feira
    - "Hoje" eh capturado automaticamente via date.today()
    - Proxima terca eh calculada (se hoje for terca, conta hoje)

INPUTS DO USUARIO (interativo OU CLI):
    - Data do fim da season (ou numero de semanas restantes)
    - Total de itens unicos no pool (default 18)
    - Lista de personagens com k inicial: [(nome, k), ...]

Autor: Bruno Pikler
Data: 2026-04-17
Referencia: Coupon Collector Problem (Mitzenmacher & Upfal, cap. 2)

CLI:
    # modo interativo (pergunta passo a passo)
    python "Simulador estatistico.py"

    # modo nao-interativo (para n8n/automacao)
    python "Simulador estatistico.py" --season-end 2026-08-01 \\
        --characters "paladin:2,warrior:1"

    # informar semanas em vez de data
    python "Simulador estatistico.py" --weeks 15 --characters "paladin:2,warrior:1"

    # JSON para pipeline
    python "Simulador estatistico.py" --season-end 2026-08-01 \\
        --characters "paladin:2,warrior:1" --json
"""

import argparse
import json
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np


# ============================================================================
# CONSTANTES
# ============================================================================
TOTAL_ITEMS_DEFAULT = 18
COSTS = {0: 0, 1: 30, 2: 150, 3: 300}  # min para s slots na semana
N_SIMS_DEFAULT = 10_000
RESET_WEEKDAY = 1  # 0=Mon, 1=Tue, ..., 6=Sun  -- terca-feira hard-coded
MINUTES_PER_TIMED_12 = 30
CRESTS_PER_TIMED_12 = 20
CRESTS_TO_UPGRADE_ITEM = 100
CREST_UNIT = CRESTS_PER_TIMED_12
CREST_UNITS_TO_UPGRADE_ITEM = CRESTS_TO_UPGRADE_ITEM // CREST_UNIT
DUNGEONS_BY_S = {
    s: COSTS[s] // MINUTES_PER_TIMED_12
    for s in COSTS
}
CRESTS_BY_S = {
    s: DUNGEONS_BY_S[s] * CRESTS_PER_TIMED_12
    for s in COSTS
}


# ============================================================================
# i18n - textos da interface e do relatorio em pt-br (default) e en-us
# Default fica em pt-br para preservar 100% do comportamento original quando
# --lang nao eh passado.
# ============================================================================
SUPPORTED_LANGS = ('pt-br', 'en-us')
DEFAULT_LANG = 'pt-br'

_T = {
    'pt-br': {
        # interactive_inputs()
        'interactive_title': 'SIMULADOR GREAT VAULT - MODO INTERATIVO',
        'today': 'Hoje',
        'next_reset': 'Proximo reset (terca)',
        'season_question': 'Quanto tempo falta para o fim da season?',
        'season_opt1': '[1] Informar a DATA do fim (DD/MM/YYYY)',
        'season_opt2': '[2] Informar o NUMERO de semanas restantes',
        'option_label': 'Opcao',
        'ask_season_end_date': 'Data do fim da season (DD/MM/YYYY)',
        'date_must_be_after': '! Data deve ser >= {date}. Tente de novo.',
        'weeks_until_end': '-> {weeks} semanas (resets) ate o fim da season',
        'ask_weeks': 'Quantas semanas restantes',
        'must_be_ge_1': '! Precisa ser >= 1.',
        'estimated_end': '-> Fim estimado: {date} (semana {weeks})',
        'invalid_number': '! Numero invalido.',
        'ask_total': 'Total de itens unicos no pool',
        'add_chars': 'Adicione seus personagens.',
        'char_format': "Formato: 'nome k maxxed' (ex: 'paladin 8 4'). ENTER vazio para encerrar.",
        'char_third_optional': 'O terceiro numero eh opcional; se omitido, maxxed=0.',
        'ask_char': 'char #{n}',
        'need_at_least_1_char': '! Precisa pelo menos 1 personagem.',
        'bad_char_format': "! Formato: 'nome k maxxed' (ex: 'paladin 8 4')",
        'k_out_of_range': '! k deve estar entre 0 e {total}.',
        'maxxed_out_of_range': '! maxxed deve estar entre 0 e k ({k}).',
        'char_added': 'OK: {name} com k={k}, maxxed={maxxed}',
        'invalid_k': '! Numero invalido para k.',
        # print_character_report()
        'character': 'PERSONAGEM',
        'k_initial': 'k inicial: {k} de {total} itens ({pct:.0f}% ja coletado)',
        'items_maxxed': 'Itens ja maxxed (6/6)',
        'free_crests_initial': 'Crests livres iniciais',
        'effective_crests_initial': 'Crests equivalentes iniciais',
        'weeks_remaining': 'Semanas restantes',
        'fixed_strategies': 'Estrategias fixas (Monte Carlo vs Markov teorico)',
        'col_mc_items': 'MC E[itens]',
        'col_markov': 'Markov',
        'col_e_upg': 'E[upg 6/6]',
        'col_crests': 'Crests',
        'col_p_upg_all': 'P(upg all)',
        'adaptive_strategies': 'Estrategias adaptativas (DP otimo)',
        'col_lambda': 'lambda',
        'col_e_items': 'E[itens]',
        'col_time': 'Tempo',
        'col_p_complete': 'P(comp)',
        'col_action_now': 'Acao agora',
        'crest_aware_strategy': 'Estrategia crest-aware (otimiza item Myth 6/6)',
        'e_looted': 'E[itens lootados]',
        'e_upgraded': 'E[itens upgrade 6/6]',
        'time_p_all': 'Tempo: {min:.0f} min  |  P(todos 6/6): {pct:.1%}',
        'max_loot_strategy': 'Estrategia max loot + crests',
        'expected_dungeons': 'Dungeons esperadas: {n:.1f}  |  Tempo: {h:.1f}h',
        'action_now_line': 'Acao agora: s={s}  |  +12 timed: {d}  |  Crests: {c}',
        'recommendation_header': '>>> RECOMENDACAO PARA ESSA SEMANA <<<',
        'play_line': 'Jogar: s = {s}  |  Tempo: {min} min',
        'timed_crests_line': '+12 timed: {d}  |  Crests: {c}',
        'p_new_item': 'P(item novo essa semana): {pct:.1%}',
        # main() report
        'json_requires_cli': 'ERRO: --json requer modo CLI nao-interativo. '
                              'Passe --season-end (ou --weeks) e --characters.',
        'report_title': 'RELATORIO GREAT VAULT',
        'season_end_label': 'Fim da season',
        'header_summary': 'Semanas restantes: {w}  |  Total itens: {t}  |  Sims: {s:,}',
        'crests_rule': 'Crests: {per_run} por +12 timed  |  '
                        '{per_item} para upgrade 1/6 -> 6/6',
        'reset_agenda': 'AGENDA DE RESETS ({n} tercas)',
        'last_marker': ' <- ULTIMA',
        'aggregated_summary': 'RESUMO AGREGADO ({n} personagens)',
        'strat_all_s2': "Estrategia 'todo s=2' (simples):",
        'strat_adaptive': 'Estrategia adaptativa (DP otimo):',
        'strat_crest_aware': 'Estrategia crest-aware (DP otimo para Myth 6/6):',
        'strat_max_loot': 'Estrategia max loot + crests:',
        'agg_time': 'Tempo: {min:.0f} min ({h:.1f}h)',
        'agg_items': 'Itens: {n:.1f}/{m} ({pct:.0f}%)',
        'agg_items_upgraded': 'Itens upgrade 6/6: {n:.1f}/{m} ({pct:.0f}%)',
        'agg_dungeons': 'Dungeons: {n:.1f}',
        'agg_looted': 'Itens lootados: {n:.1f}/{m} ({pct:.0f}%)',
        'actions_for_week': 'ACOES PARA A SEMANA QUE COMECA EM {date}',
        'action_line': '{name:<15} (k={k:>2}): jogar s={s}  '
                        '({min:>3} min, {c:>3} crests, '
                        '{pct:.0%} de chance de item novo)',
        'total_label': '>>> TOTAL',
        'total_week_line': '{min} min essa semana ({h:.1f}h)',
        'actions_max_loot': 'ACOES MAX LOOT + CRESTS PARA ESSA SEMANA:',
        'action_max_line': '{name:<15} (k={k:>2}): jogar s={s}  '
                            '({d:>2} dungeons, {min:>3} min, {c:>3} crests)',
        'total_max_line': '{d} dungeons, {min} min essa semana ({h:.1f}h)',
    },
    'en-us': {
        'interactive_title': 'GREAT VAULT SIMULATOR - INTERACTIVE MODE',
        'today': 'Today',
        'next_reset': 'Next reset (Tuesday)',
        'season_question': 'How much time is left in the season?',
        'season_opt1': '[1] Provide season END DATE (DD/MM/YYYY)',
        'season_opt2': '[2] Provide NUMBER of weeks remaining',
        'option_label': 'Choice',
        'ask_season_end_date': 'Season end date (DD/MM/YYYY)',
        'date_must_be_after': '! Date must be >= {date}. Try again.',
        'weeks_until_end': '-> {weeks} weeks (resets) until end of season',
        'ask_weeks': 'How many weeks remaining',
        'must_be_ge_1': '! Must be >= 1.',
        'estimated_end': '-> Estimated end: {date} (week {weeks})',
        'invalid_number': '! Invalid number.',
        'ask_total': 'Total unique items in the pool',
        'add_chars': 'Add your characters.',
        'char_format': "Format: 'name k maxxed' (e.g. 'paladin 8 4'). Empty ENTER to finish.",
        'char_third_optional': 'Third number is optional; if omitted, maxxed=0.',
        'ask_char': 'char #{n}',
        'need_at_least_1_char': '! Need at least 1 character.',
        'bad_char_format': "! Format: 'name k maxxed' (e.g. 'paladin 8 4')",
        'k_out_of_range': '! k must be between 0 and {total}.',
        'maxxed_out_of_range': '! maxxed must be between 0 and k ({k}).',
        'char_added': 'OK: {name} with k={k}, maxxed={maxxed}',
        'invalid_k': '! Invalid number for k.',
        'character': 'CHARACTER',
        'k_initial': 'starting k: {k} of {total} items ({pct:.0f}% already collected)',
        'items_maxxed': 'Items already maxxed (6/6)',
        'free_crests_initial': 'Initial free crests',
        'effective_crests_initial': 'Initial equivalent crests',
        'weeks_remaining': 'Weeks remaining',
        'fixed_strategies': 'Fixed strategies (Monte Carlo vs theoretical Markov)',
        'col_mc_items': 'MC E[items]',
        'col_markov': 'Markov',
        'col_e_upg': 'E[upg 6/6]',
        'col_crests': 'Crests',
        'col_p_upg_all': 'P(upg all)',
        'adaptive_strategies': 'Adaptive strategies (optimal DP)',
        'col_lambda': 'lambda',
        'col_e_items': 'E[items]',
        'col_time': 'Time',
        'col_p_complete': 'P(comp)',
        'col_action_now': 'Action now',
        'crest_aware_strategy': 'Crest-aware strategy (optimizes Myth 6/6 items)',
        'e_looted': 'E[looted items]',
        'e_upgraded': 'E[items upgraded to 6/6]',
        'time_p_all': 'Time: {min:.0f} min  |  P(all 6/6): {pct:.1%}',
        'max_loot_strategy': 'Max loot + crests strategy',
        'expected_dungeons': 'Expected dungeons: {n:.1f}  |  Time: {h:.1f}h',
        'action_now_line': 'Action now: s={s}  |  +12 timed: {d}  |  Crests: {c}',
        'recommendation_header': '>>> RECOMMENDATION FOR THIS WEEK <<<',
        'play_line': 'Play: s = {s}  |  Time: {min} min',
        'timed_crests_line': '+12 timed: {d}  |  Crests: {c}',
        'p_new_item': 'P(new item this week): {pct:.1%}',
        'json_requires_cli': 'ERROR: --json requires non-interactive CLI mode. '
                              'Pass --season-end (or --weeks) and --characters.',
        'report_title': 'GREAT VAULT REPORT',
        'season_end_label': 'Season end',
        'header_summary': 'Weeks remaining: {w}  |  Total items: {t}  |  Sims: {s:,}',
        'crests_rule': 'Crests: {per_run} per +12 timed  |  '
                        '{per_item} for upgrade 1/6 -> 6/6',
        'reset_agenda': 'RESET SCHEDULE ({n} Tuesdays)',
        'last_marker': ' <- LAST',
        'aggregated_summary': 'AGGREGATED SUMMARY ({n} characters)',
        'strat_all_s2': "'All s=2' strategy (simple):",
        'strat_adaptive': 'Adaptive strategy (optimal DP):',
        'strat_crest_aware': 'Crest-aware strategy (optimal DP for Myth 6/6):',
        'strat_max_loot': 'Max loot + crests strategy:',
        'agg_time': 'Time: {min:.0f} min ({h:.1f}h)',
        'agg_items': 'Items: {n:.1f}/{m} ({pct:.0f}%)',
        'agg_items_upgraded': 'Items upgraded to 6/6: {n:.1f}/{m} ({pct:.0f}%)',
        'agg_dungeons': 'Dungeons: {n:.1f}',
        'agg_looted': 'Looted items: {n:.1f}/{m} ({pct:.0f}%)',
        'actions_for_week': 'ACTIONS FOR THE WEEK STARTING {date}',
        'action_line': '{name:<15} (k={k:>2}): play s={s}  '
                        '({min:>3} min, {c:>3} crests, '
                        '{pct:.0%} chance of new item)',
        'total_label': '>>> TOTAL',
        'total_week_line': '{min} min this week ({h:.1f}h)',
        'actions_max_loot': 'MAX LOOT + CRESTS ACTIONS FOR THIS WEEK:',
        'action_max_line': '{name:<15} (k={k:>2}): play s={s}  '
                            '({d:>2} dungeons, {min:>3} min, {c:>3} crests)',
        'total_max_line': '{d} dungeons, {min} min this week ({h:.1f}h)',
    },
}


def t(lang, key, **kwargs):
    """Retorna texto localizado para (lang, key), formatado com kwargs."""
    table = _T.get(lang) or _T[DEFAULT_LANG]
    template = table.get(key) or _T[DEFAULT_LANG].get(key) or key
    return template.format(**kwargs) if kwargs else template


# ============================================================================
# Funcao: calcula a proxima terca-feira a partir de uma data
# (Se hoje for terca, retorna hoje - assume que o reset ja aconteceu)
# ============================================================================
def next_tuesday(today: date) -> date:
    """Retorna a proxima terca-feira >= today."""
    days_ahead = (RESET_WEEKDAY - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


# ============================================================================
# Funcao: conta quantas tercas cabem entre next_reset e season_end (inclusive)
# Cada terca eh uma janela de loot. Ultima semana pode ser parcial.
# ============================================================================
def weeks_remaining(next_reset: date, season_end: date) -> int:
    """Conta resets de terca a partir de next_reset ate season_end."""
    if next_reset > season_end:
        return 0
    days_span = (season_end - next_reset).days
    return days_span // 7 + 1


# ============================================================================
# Funcao: lista as datas dos resets (para imprimir agenda)
# ============================================================================
def list_reset_dates(next_reset: date, season_end: date) -> List[date]:
    """Retorna lista de datas das tercas entre next_reset e season_end."""
    dates = []
    current = next_reset
    while current <= season_end:
        dates.append(current)
        current += timedelta(days=7)
    return dates


# ============================================================================
# Funcao: parsea data em formatos flexiveis (DD/MM/YYYY ou YYYY-MM-DD)
# ============================================================================
def parse_date_flexible(s: str) -> date:
    """Aceita 'DD/MM/YYYY', 'DD-MM-YYYY' ou 'YYYY-MM-DD'."""
    s = s.strip()
    # tenta ISO primeiro
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    # tenta DD/MM/YYYY ou DD-MM-YYYY
    for sep in ['/', '-']:
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                try:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    if y < 100:  # 26 -> 2026
                        y += 2000
                    return date(y, m, d)
                except ValueError:
                    continue
    raise ValueError(f"Data invalida: '{s}'. Use DD/MM/YYYY ou YYYY-MM-DD.")


# ============================================================================
# Funcao: parsea string "paladin:2,warrior:1" em [(nome, k), ...]
# ============================================================================
def parse_characters(s: str) -> List[Tuple[str, int]]:
    """Parseia spec de personagens em lista (nome, k_inicial)."""
    chars = []
    for part in s.split(','):
        if not part.strip():
            continue
        name, k_str = part.strip().split(':')
        chars.append((name.strip(), int(k_str.strip())))
    return chars


def parse_character_crests(s: Optional[str]) -> Dict[str, int]:
    """Parseia spec opcional de crests em dict nome -> crests."""
    if not s:
        return {}
    crests = {}
    for part in s.split(','):
        if not part.strip():
            continue
        name, crest_str = part.strip().split(':')
        crests[name.strip()] = int(crest_str.strip())
    return crests


def parse_character_maxxed(s: Optional[str]) -> Dict[str, int]:
    """Parseia spec opcional de itens ja maximizados em dict nome -> maxxed."""
    if not s:
        return {}
    maxxed = {}
    for part in s.split(','):
        if not part.strip():
            continue
        name, maxxed_str = part.strip().split(':')
        maxxed[name.strip()] = int(maxxed_str.strip())
    return maxxed


def crests_to_units(crests: int) -> int:
    """Converte crests para unidades de 20, arredondando para baixo."""
    return max(0, crests // CREST_UNIT)


def upgraded_items_from_crests(k: int, crest_units: int) -> int:
    """Itens Myth efetivamente upgradeados para 100."""
    return min(k, crest_units // CREST_UNITS_TO_UPGRADE_ITEM)


def effective_crests(initial_crests: int, initial_maxxed_items: int) -> int:
    """Crests equivalentes: upgrades ja feitos + crests ainda disponiveis."""
    return initial_crests + initial_maxxed_items * CRESTS_TO_UPGRADE_ITEM


# ============================================================================
# Modo INTERATIVO: pergunta os inputs ao usuario passo a passo
# ============================================================================
def interactive_inputs(lang: str = DEFAULT_LANG) -> Dict:
    """Conduz o usuario pelos inputs e retorna config completa."""
    print("=" * 70)
    print(f"  {t(lang, 'interactive_title')}")
    print("=" * 70)

    today = date.today()
    next_reset = next_tuesday(today)
    print(f"\n  {t(lang, 'today')}: {today.strftime('%d/%m/%Y (%A)')}")
    print(f"  {t(lang, 'next_reset')}: {next_reset.strftime('%d/%m/%Y')}")

    # ------ semanas restantes (via data ou direto) ----------------------------
    print(f"\n  {t(lang, 'season_question')}")
    print(f"    {t(lang, 'season_opt1')}")
    print(f"    {t(lang, 'season_opt2')}")
    choice = input(f"  {t(lang, 'option_label')} [1]: ").strip() or "1"

    if choice == "1":
        while True:
            s = input(f"  {t(lang, 'ask_season_end_date')}: ").strip()
            try:
                season_end = parse_date_flexible(s)
                if season_end < next_reset:
                    print(f"  {t(lang, 'date_must_be_after', date=next_reset.strftime('%d/%m/%Y'))}")
                    continue
                weeks = weeks_remaining(next_reset, season_end)
                print(f"  {t(lang, 'weeks_until_end', weeks=weeks)}")
                break
            except ValueError as e:
                print(f"  ! {e}")
    else:
        while True:
            try:
                weeks = int(input(f"  {t(lang, 'ask_weeks')}? ").strip())
                if weeks < 1:
                    print(f"  {t(lang, 'must_be_ge_1')}")
                    continue
                # estima data do fim a partir do numero de semanas
                season_end = next_reset + timedelta(days=7 * (weeks - 1))
                print(f"  {t(lang, 'estimated_end', date=season_end.strftime('%d/%m/%Y'), weeks=weeks)}")
                break
            except ValueError:
                print(f"  {t(lang, 'invalid_number')}")

    # ------ total de itens ----------------------------------------------------
    while True:
        s = input(f"\n  {t(lang, 'ask_total')} [{TOTAL_ITEMS_DEFAULT}]: ").strip()
        if not s:
            total = TOTAL_ITEMS_DEFAULT
            break
        try:
            total = int(s)
            if total < 1:
                print(f"  {t(lang, 'must_be_ge_1')}")
                continue
            break
        except ValueError:
            print(f"  {t(lang, 'invalid_number')}")

    # ------ personagens (loop ate vazio) --------------------------------------
    print(f"\n  {t(lang, 'add_chars')}")
    print(f"  {t(lang, 'char_format')}")
    print(f"  {t(lang, 'char_third_optional')}")
    characters = []
    character_maxxed = {}
    while True:
        line = input(f"  {t(lang, 'ask_char', n=len(characters) + 1)}: ").strip()
        if not line:
            if characters:
                break
            print(f"  {t(lang, 'need_at_least_1_char')}")
            continue
        parts = line.replace(':', ' ').split()
        if len(parts) < 2:
            print(f"  {t(lang, 'bad_char_format')}")
            continue
        try:
            name = parts[0]
            k = int(parts[1])
            maxxed = int(parts[2]) if len(parts) >= 3 else 0
            if not (0 <= k <= total):
                print(f"  {t(lang, 'k_out_of_range', total=total)}")
                continue
            if not (0 <= maxxed <= k):
                print(f"  {t(lang, 'maxxed_out_of_range', k=k)}")
                continue
            characters.append((name, k))
            character_maxxed[name] = maxxed
            print(f"    {t(lang, 'char_added', name=name, k=k, maxxed=maxxed)}")
        except ValueError:
            print(f"  {t(lang, 'invalid_k')}")

    return {
        'today': today,
        'next_reset': next_reset,
        'season_end': season_end,
        'weeks': weeks,
        'total': total,
        'characters': characters,
        'character_crests': {},
        'character_maxxed': character_maxxed,
    }


# ============================================================================
# P(novo): probabilidade de pelo menos 1 dos s slots ser item novo, dado k
# ============================================================================
def p_new(k: int, s: int, total: int) -> float:
    """Bernoulli: prob de avancar k -> k+1 nessa semana."""
    if s == 0:
        return 0.0
    return 1.0 - (k / total) ** s


# ============================================================================
# CADEIA DE MARKOV: distribuicao exata de k apos w semanas com estrategia s
# ============================================================================
def markov_distribution(s: int, weeks: int, total: int,
                        k_inicial: int = 0) -> np.ndarray:
    """Propaga distribuicao de k. P[k] = Prob(estar em k apos weeks semanas)."""
    P = np.zeros(total + 1)
    P[k_inicial] = 1.0
    for _ in range(weeks):
        new_P = np.zeros(total + 1)
        for k in range(total + 1):
            p = p_new(k, s, total)
            new_P[k] += P[k] * (1 - p)
            if k < total:
                new_P[k + 1] += P[k] * p
        P = new_P
    return P


# ============================================================================
# E[itens] e P(completa) via cadeia de Markov - exato
# ============================================================================
def markov_stats(s: int, weeks: int, total: int,
                 k_inicial: int = 0) -> Tuple[float, float]:
    """Retorna (E[itens_finais], P(coletou todos))."""
    P = markov_distribution(s, weeks, total, k_inicial)
    expected = float(np.sum(np.arange(total + 1) * P))
    p_complete = float(P[total])
    return expected, p_complete


def markov_upgrade_stats(s: int, weeks: int, total: int,
                         k_inicial: int = 0,
                         initial_crests: int = 0) -> Tuple[float, float, int]:
    """Retorna E[itens upgradeados], P(todos upgradeados), crests finais."""
    P = markov_distribution(s, weeks, total, k_inicial)
    crest_units = crests_to_units(initial_crests + weeks * CRESTS_BY_S[s])
    upgraded_by_k = np.array([
        upgraded_items_from_crests(k, crest_units)
        for k in range(total + 1)
    ])
    expected_upgraded = float(np.sum(upgraded_by_k * P))
    p_all_upgraded = float(P[total]) if upgraded_items_from_crests(total, crest_units) == total else 0.0
    return expected_upgraded, p_all_upgraded, crest_units * CREST_UNIT


# ============================================================================
# Monte Carlo: simula UMA season com estrategia FIXA (com early stop)
# ============================================================================
def simulate_fixed(s: int, weeks: int, total: int,
                   rng: np.random.Generator,
                   k_inicial: int = 0) -> Tuple[int, int]:
    """Simula 1 season. Retorna (k_final, tempo_em_minutos)."""
    owned = set(range(k_inicial))
    time_spent = 0
    for _ in range(weeks):
        if len(owned) >= total:
            break
        draws = rng.integers(0, total, size=s)
        for d in draws:
            if int(d) not in owned:
                owned.add(int(d))
                break
        time_spent += COSTS[s]
    return len(owned), time_spent


# ============================================================================
# DP: resolve politica otima maximizando E[itens] - lambda * E[tempo]
# ============================================================================
def solve_optimal_policy(lambda_cost: float, weeks: int,
                         total: int) -> Tuple[np.ndarray, np.ndarray]:
    """Bellman backward induction. Terminal V(k, 0) = k."""
    V = np.zeros((total + 1, weeks + 1))
    policy = np.zeros((total + 1, weeks + 1), dtype=int)
    for k in range(total + 1):
        V[k, 0] = k
    for w in range(1, weeks + 1):
        for k in range(total + 1):
            if k == total:
                V[k, w] = total
                policy[k, w] = 0
                continue
            best_value = -np.inf
            best_s = 0
            for s in [0, 1, 2, 3]:
                p = p_new(k, s, total)
                cost = COSTS[s]
                next_k = min(k + 1, total)
                value = (-lambda_cost * cost
                         + p * V[next_k, w - 1]
                         + (1 - p) * V[k, w - 1])
                if value > best_value:
                    best_value = value
                    best_s = s
            V[k, w] = best_value
            policy[k, w] = best_s
    return policy, V


def solve_optimal_policy_with_crests(lambda_cost: float, weeks: int,
                                     total: int,
                                     initial_crests: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """Bellman com estado (k, crests) maximizando itens upgradeados para 100."""
    max_crest_units = total * CREST_UNITS_TO_UPGRADE_ITEM
    initial_units = min(crests_to_units(initial_crests), max_crest_units)
    V = np.zeros((total + 1, max_crest_units + 1, weeks + 1))
    policy = np.zeros((total + 1, max_crest_units + 1, weeks + 1), dtype=int)

    for k in range(total + 1):
        for c in range(max_crest_units + 1):
            V[k, c, 0] = upgraded_items_from_crests(k, c)

    for w in range(1, weeks + 1):
        for k in range(total + 1):
            for c in range(max_crest_units + 1):
                best_value = -np.inf
                best_s = 0
                for s in [0, 1, 2, 3]:
                    p = p_new(k, s, total)
                    cost = COSTS[s]
                    crest_units_next = min(
                        c + crests_to_units(CRESTS_BY_S[s]),
                        max_crest_units
                    )
                    next_k = min(k + 1, total)
                    value = (-lambda_cost * cost
                             + p * V[next_k, crest_units_next, w - 1]
                             + (1 - p) * V[k, crest_units_next, w - 1])
                    if value > best_value:
                        best_value = value
                        best_s = s
                V[k, c, w] = best_value
                policy[k, c, w] = best_s

    # Mantem initial_units referenciado no docstring/depuracao e evita alerta mental
    _ = initial_units
    return policy, V


def solve_max_loot_then_crests_policy(weeks: int, total: int) -> np.ndarray:
    """
    Bellman lexicografico com estado (k, crests):
    1) maximiza E[itens lootados]
    2) maximiza E[itens upgradeados para 100]
    3) minimiza E[tempo] entre politicas equivalentes
    """
    max_crest_units = total * CREST_UNITS_TO_UPGRADE_ITEM
    V_loot = np.zeros((total + 1, max_crest_units + 1, weeks + 1))
    V_upgraded = np.zeros((total + 1, max_crest_units + 1, weeks + 1))
    V_time = np.zeros((total + 1, max_crest_units + 1, weeks + 1))
    policy = np.zeros((total + 1, max_crest_units + 1, weeks + 1), dtype=int)

    for k in range(total + 1):
        for c in range(max_crest_units + 1):
            V_loot[k, c, 0] = k
            V_upgraded[k, c, 0] = upgraded_items_from_crests(k, c)

    eps = 1e-12
    for w in range(1, weeks + 1):
        for k in range(total + 1):
            for c in range(max_crest_units + 1):
                best_tuple = (-np.inf, -np.inf, np.inf)
                best_s = 0
                for s in [0, 1, 2, 3]:
                    p = p_new(k, s, total)
                    next_k = min(k + 1, total)
                    next_c = min(
                        c + crests_to_units(CRESTS_BY_S[s]),
                        max_crest_units
                    )
                    expected_loot = (
                        p * V_loot[next_k, next_c, w - 1]
                        + (1 - p) * V_loot[k, next_c, w - 1]
                    )
                    expected_upgraded = (
                        p * V_upgraded[next_k, next_c, w - 1]
                        + (1 - p) * V_upgraded[k, next_c, w - 1]
                    )
                    expected_time = (
                        COSTS[s]
                        + p * V_time[next_k, next_c, w - 1]
                        + (1 - p) * V_time[k, next_c, w - 1]
                    )

                    is_better = (
                        expected_loot > best_tuple[0] + eps
                        or (
                            abs(expected_loot - best_tuple[0]) <= eps
                            and expected_upgraded > best_tuple[1] + eps
                        )
                        or (
                            abs(expected_loot - best_tuple[0]) <= eps
                            and abs(expected_upgraded - best_tuple[1]) <= eps
                            and expected_time < best_tuple[2] - eps
                        )
                    )
                    if is_better:
                        best_tuple = (expected_loot, expected_upgraded, expected_time)
                        best_s = s

                V_loot[k, c, w] = best_tuple[0]
                V_upgraded[k, c, w] = best_tuple[1]
                V_time[k, c, w] = best_tuple[2]
                policy[k, c, w] = best_s

    return policy


# ============================================================================
# Projeta E[itens], E[tempo] e P(completa) seguindo politica adaptativa
# ============================================================================
def project_adaptive(policy: np.ndarray, weeks: int, total: int,
                     k_inicial: int) -> Tuple[float, float, float]:
    """Retorna (E[itens_finais], E[tempo_total], P(completa))."""
    P = np.zeros(total + 1)
    P[k_inicial] = 1.0
    expected_time = 0.0
    for week_idx in range(weeks):
        weeks_left_local = weeks - week_idx
        new_P = np.zeros(total + 1)
        for k in range(total + 1):
            if P[k] == 0:
                continue
            s = int(policy[k, weeks_left_local])
            expected_time += P[k] * COSTS[s]
            p = p_new(k, s, total)
            new_P[k] += P[k] * (1 - p)
            if k < total:
                new_P[k + 1] += P[k] * p
        P = new_P
    expected_items = float(np.sum(np.arange(total + 1) * P))
    return expected_items, expected_time, float(P[total])


def project_adaptive_with_crests(policy: np.ndarray, weeks: int, total: int,
                                 k_inicial: int,
                                 initial_crests: int) -> Tuple[float, float, float, float]:
    """Projeta politica crest-aware. Retorna E[loot], E[upg], E[tempo], P(todos upg)."""
    max_crest_units = total * CREST_UNITS_TO_UPGRADE_ITEM
    P = np.zeros((total + 1, max_crest_units + 1))
    start_units = min(crests_to_units(initial_crests), max_crest_units)
    P[k_inicial, start_units] = 1.0
    expected_time = 0.0

    for week_idx in range(weeks):
        weeks_left_local = weeks - week_idx
        new_P = np.zeros((total + 1, max_crest_units + 1))
        for k in range(total + 1):
            for crest_units in range(max_crest_units + 1):
                prob_state = P[k, crest_units]
                if prob_state == 0:
                    continue
                s = int(policy[k, crest_units, weeks_left_local])
                expected_time += prob_state * COSTS[s]
                next_crests = min(
                    crest_units + crests_to_units(CRESTS_BY_S[s]),
                    max_crest_units
                )
                p = p_new(k, s, total)
                new_P[k, next_crests] += prob_state * (1 - p)
                if k < total:
                    new_P[k + 1, next_crests] += prob_state * p
        P = new_P

    expected_looted = 0.0
    expected_upgraded = 0.0
    p_all_upgraded = 0.0
    for k in range(total + 1):
        for crest_units in range(max_crest_units + 1):
            prob_state = P[k, crest_units]
            if prob_state == 0:
                continue
            expected_looted += prob_state * k
            upgraded = upgraded_items_from_crests(k, crest_units)
            expected_upgraded += prob_state * upgraded
            if upgraded == total:
                p_all_upgraded += prob_state

    return (
        float(expected_looted),
        float(expected_upgraded),
        expected_time,
        float(p_all_upgraded),
    )


def project_policy_with_crests(policy: np.ndarray, weeks: int, total: int,
                               k_inicial: int,
                               initial_crests: int) -> Tuple[float, float, float, float, float]:
    """Projeta politica com estado (k, crests). Retorna E[loot], E[upg], E[tempo], E[dungeons], P(todos upg)."""
    max_crest_units = total * CREST_UNITS_TO_UPGRADE_ITEM
    P = np.zeros((total + 1, max_crest_units + 1))
    start_units = min(crests_to_units(initial_crests), max_crest_units)
    P[k_inicial, start_units] = 1.0
    expected_time = 0.0
    expected_dungeons = 0.0

    for week_idx in range(weeks):
        weeks_left_local = weeks - week_idx
        new_P = np.zeros((total + 1, max_crest_units + 1))
        for k in range(total + 1):
            for crest_units in range(max_crest_units + 1):
                prob_state = P[k, crest_units]
                if prob_state == 0:
                    continue
                s = int(policy[k, crest_units, weeks_left_local])
                expected_time += prob_state * COSTS[s]
                expected_dungeons += prob_state * DUNGEONS_BY_S[s]
                next_crests = min(
                    crest_units + crests_to_units(CRESTS_BY_S[s]),
                    max_crest_units
                )
                p = p_new(k, s, total)
                new_P[k, next_crests] += prob_state * (1 - p)
                if k < total:
                    new_P[k + 1, next_crests] += prob_state * p
        P = new_P

    expected_looted = 0.0
    expected_upgraded = 0.0
    p_all_upgraded = 0.0
    for k in range(total + 1):
        for crest_units in range(max_crest_units + 1):
            prob_state = P[k, crest_units]
            if prob_state == 0:
                continue
            upgraded = upgraded_items_from_crests(k, crest_units)
            expected_looted += prob_state * k
            expected_upgraded += prob_state * upgraded
            if upgraded == total:
                p_all_upgraded += prob_state

    return (
        float(expected_looted),
        float(expected_upgraded),
        expected_time,
        expected_dungeons,
        float(p_all_upgraded),
    )


# ============================================================================
# Resumo legivel da policy[k, w] (auditoria humana)
# ============================================================================
def summarize_policy(policy: np.ndarray, weeks: int, total: int) -> Dict:
    sample_w = sorted({
        w for w in [weeks, weeks // 2, max(weeks // 4, 1), 5, 1]
        if 1 <= w <= weeks
    })
    sample_k = sorted(set([0, total // 4, total // 2, 3 * total // 4, total - 1]))
    return {f'w={w}': {f'k={k}': int(policy[k, w]) for k in sample_k}
            for w in sample_w}


# ============================================================================
# Analise completa para UM personagem
# ============================================================================
def analyze_character(name: str, k_inicial: int, weeks: int, total: int,
                      n_sims: int, seed: int,
                      initial_crests: int = 0,
                      initial_maxxed_items: int = 0) -> Dict:
    """Roda comparacao completa para um personagem."""
    if initial_maxxed_items < 0 or initial_maxxed_items > k_inicial:
        raise ValueError(
            f"{name}: maxxed ({initial_maxxed_items}) deve estar entre 0 e k ({k_inicial})"
        )
    effective_initial_crests = effective_crests(initial_crests, initial_maxxed_items)
    rng = np.random.default_rng(seed)
    result = {
        'name': name,
        'k_inicial': k_inicial,
        'initial_crests': initial_crests,
        'initial_maxxed_items': initial_maxxed_items,
        'effective_initial_crests': effective_initial_crests,
        'weeks_remaining': weeks,
        'fixed': {},
        'adaptive': {},
        'crest_aware': {},
        'max_loot_then_crests': {},
    }

    # estrategias fixas
    for s in [1, 2, 3]:
        items_mc = np.zeros(n_sims, dtype=int)
        times_mc = np.zeros(n_sims, dtype=int)
        for i in range(n_sims):
            k_f, t = simulate_fixed(s, weeks, total, rng, k_inicial)
            items_mc[i] = k_f
            times_mc[i] = t
        e_markov, p_markov = markov_stats(s, weeks, total, k_inicial)
        e_upgraded, p_all_upgraded, final_crests = markov_upgrade_stats(
            s, weeks, total, k_inicial, effective_initial_crests
        )
        result['fixed'][f's={s}'] = {
            'mean_items_mc': float(np.mean(items_mc)),
            'mean_time_min': float(np.mean(times_mc)),
            'p_complete_mc': float(np.mean(items_mc == total)),
            'theoretical_items_markov': round(e_markov, 3),
            'theoretical_p_complete': round(p_markov, 4),
            'expected_upgraded_items': round(e_upgraded, 3),
            'theoretical_p_all_upgraded': round(p_all_upgraded, 4),
            'final_crests': final_crests,
        }

    # estrategias adaptativas (varios lambda)
    for lam in [0.0, 0.0001, 0.0005, 0.001, 0.002, 0.005]:
        policy, _ = solve_optimal_policy(lam, weeks, total)
        e_proj, t_proj, p_proj = project_adaptive(policy, weeks, total, k_inicial)
        result['adaptive'][f'lambda={lam}'] = {
            'expected_items': round(e_proj, 3),
            'expected_time_min': round(t_proj, 1),
            'p_complete': round(p_proj, 4),
            'action_this_week': int(policy[k_inicial, weeks]),
            'time_this_week_min': COSTS[int(policy[k_inicial, weeks])],
            'policy_table': summarize_policy(policy, weeks, total),
        }

    # politica crest-aware (sweet spot lambda=0.0005)
    crest_policy, _ = solve_optimal_policy_with_crests(
        0.0005, weeks, total, effective_initial_crests
    )
    e_looted_c, e_upgraded_c, t_c, p_all_c = project_adaptive_with_crests(
        crest_policy, weeks, total, k_inicial, effective_initial_crests
    )
    initial_units = min(
        crests_to_units(effective_initial_crests),
        total * CREST_UNITS_TO_UPGRADE_ITEM
    )
    s_crest_rec = int(crest_policy[k_inicial, initial_units, weeks])
    result['crest_aware']['lambda=0.0005'] = {
        'expected_looted_items': round(e_looted_c, 3),
        'expected_upgraded_items': round(e_upgraded_c, 3),
        'expected_time_min': round(t_c, 1),
        'p_all_upgraded': round(p_all_c, 4),
        'action_this_week': s_crest_rec,
        'time_this_week_min': COSTS[s_crest_rec],
        'crests_this_week': CRESTS_BY_S[s_crest_rec],
    }

    max_policy = solve_max_loot_then_crests_policy(weeks, total)
    e_looted_m, e_upgraded_m, t_m, dungeons_m, p_all_m = project_policy_with_crests(
        max_policy, weeks, total, k_inicial, effective_initial_crests
    )
    s_max_rec = int(max_policy[k_inicial, initial_units, weeks])
    result['max_loot_then_crests'] = {
        'expected_looted_items': round(e_looted_m, 3),
        'expected_upgraded_items': round(e_upgraded_m, 3),
        'expected_time_min': round(t_m, 1),
        'expected_time_hours': round(t_m / 60, 1),
        'expected_dungeons': round(dungeons_m, 1),
        'p_all_upgraded': round(p_all_m, 4),
        'action_this_week': s_max_rec,
        'time_this_week_min': COSTS[s_max_rec],
        'dungeons_this_week': DUNGEONS_BY_S[s_max_rec],
        'crests_this_week': CRESTS_BY_S[s_max_rec],
    }

    # recomendacao para essa semana (crest-aware)
    s_rec = s_crest_rec
    result['recommendation_this_week'] = {
        'play_s': s_rec,
        'time_min': COSTS[s_rec],
        'timed_12_keys': DUNGEONS_BY_S[s_rec],
        'crests': CRESTS_BY_S[s_rec],
        'p_new_item': round(p_new(k_inicial, s_rec, total), 3),
    }
    return result


# ============================================================================
# Print formatado para UM personagem
# ============================================================================
def print_character_report(char: Dict, total: int, lang: str = DEFAULT_LANG):
    print(f"\n{'=' * 70}")
    print(f"  {t(lang, 'character')}: {char['name'].upper()}")
    print(f"  {t(lang, 'k_initial', k=char['k_inicial'], total=total, pct=100 * char['k_inicial'] / total)}")
    print(f"  {t(lang, 'items_maxxed')}: {char.get('initial_maxxed_items', 0)}")
    print(f"  {t(lang, 'free_crests_initial')}: {char.get('initial_crests', 0)}")
    print(f"  {t(lang, 'effective_crests_initial')}: {char.get('effective_initial_crests', 0)}")
    print(f"  {t(lang, 'weeks_remaining')}: {char['weeks_remaining']}")
    print(f"{'=' * 70}")

    print(f"\n  {t(lang, 'fixed_strategies')}")
    print(f"  {'s':<4} {t(lang, 'col_mc_items'):>12} {t(lang, 'col_markov'):>10} "
          f"{t(lang, 'col_e_upg'):>11} {t(lang, 'col_crests'):>8} {t(lang, 'col_p_upg_all'):>11}")
    print(f"  {'-' * 70}")
    for s_name, r in char['fixed'].items():
        print(f"  {s_name:<4} {r['mean_items_mc']:>12.2f} "
              f"{r['theoretical_items_markov']:>10.2f} "
              f"{r['expected_upgraded_items']:>11.2f} "
              f"{r['final_crests']:>8.0f} {r['theoretical_p_all_upgraded']:>11.1%}")

    print(f"\n  {t(lang, 'adaptive_strategies')}")
    print(f"  {t(lang, 'col_lambda'):<14} {t(lang, 'col_e_items'):>10} {t(lang, 'col_time'):>13} "
          f"{t(lang, 'col_p_complete'):>10} {t(lang, 'col_action_now'):>12}")
    print(f"  {'-' * 60}")
    for lam_name, r in char['adaptive'].items():
        print(f"  {lam_name:<14} {r['expected_items']:>10.2f} "
              f"{r['expected_time_min']:>9.0f} min {r['p_complete']:>10.1%} "
              f"{'s=' + str(r['action_this_week']):>12}")

    crest = char['crest_aware']['lambda=0.0005']
    print(f"\n  {t(lang, 'crest_aware_strategy')}")
    print(f"      {t(lang, 'e_looted')}: {crest['expected_looted_items']:.2f}")
    print(f"      {t(lang, 'e_upgraded')}: {crest['expected_upgraded_items']:.2f}")
    print(f"      {t(lang, 'time_p_all', min=crest['expected_time_min'], pct=crest['p_all_upgraded'])}")

    max_crest = char['max_loot_then_crests']
    print(f"\n  {t(lang, 'max_loot_strategy')}")
    print(f"      {t(lang, 'e_looted')}: {max_crest['expected_looted_items']:.2f}")
    print(f"      {t(lang, 'e_upgraded')}: {max_crest['expected_upgraded_items']:.2f}")
    print(f"      {t(lang, 'expected_dungeons', n=max_crest['expected_dungeons'], h=max_crest['expected_time_hours'])}")
    print(f"      {t(lang, 'action_now_line', s=max_crest['action_this_week'], d=max_crest['dungeons_this_week'], c=max_crest['crests_this_week'])}")

    rec = char['recommendation_this_week']
    print(f"\n  {t(lang, 'recommendation_header')}")
    print(f"      {t(lang, 'play_line', s=rec['play_s'], min=rec['time_min'])}")
    print(f"      {t(lang, 'timed_crests_line', d=rec['timed_12_keys'], c=rec['crests'])}")
    print(f"      {t(lang, 'p_new_item', pct=rec['p_new_item'])}")


# ============================================================================
# CLI principal
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description='Simulador Great Vault WoW - multi-character',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
    # MODO INTERATIVO (default - pergunta passo a passo)
    python "Simulador estatistico.py"

    # MODO CLI (nao-interativo, para automacao/n8n)
    python "Simulador estatistico.py" --season-end 2026-08-01 \\
        --characters "paladin:2,warrior:1"

    # informar semanas em vez de data
    python "Simulador estatistico.py" --weeks 15 \\
        --characters "paladin:2,warrior:1"

    # JSON estruturado
    python "Simulador estatistico.py" --season-end 2026-08-01 \\
        --characters "paladin:2,warrior:1" --json
""")
    parser.add_argument('--season-end', type=str, default=None,
                        help='data do fim da season (DD/MM/YYYY ou YYYY-MM-DD)')
    parser.add_argument('--weeks', type=int, default=None,
                        help='numero de semanas restantes (alternativa a --season-end)')
    parser.add_argument('--characters', type=str, default=None,
                        help='lista nome:k (ex: "paladin:2,warrior:1")')
    parser.add_argument('--crests', type=str, default=None,
                        help='crests atuais por personagem (ex: "paladin:40,warrior:80"). Default: 0')
    parser.add_argument('--maxxed', type=str, default=None,
                        help='itens Myth ja maximizados por personagem (ex: "paladin:4,warrior:2"). Default: 0')
    parser.add_argument('--total', type=int, default=TOTAL_ITEMS_DEFAULT,
                        help=f'total de itens unicos no pool (default: {TOTAL_ITEMS_DEFAULT})')
    parser.add_argument('--sims', type=int, default=N_SIMS_DEFAULT,
                        help=f'numero de simulacoes MC (default: {N_SIMS_DEFAULT})')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--json', action='store_true',
                        help='saida JSON estruturada (para n8n/API)')
    parser.add_argument('--interactive', action='store_true',
                        help='forca modo interativo mesmo se houver args CLI')
    parser.add_argument('--lang', choices=SUPPORTED_LANGS, default=DEFAULT_LANG,
                        help=f'idioma do relatorio / report language (default: {DEFAULT_LANG})')
    args = parser.parse_args()
    lang = args.lang

    # ------ decide modo: interativo ou CLI ------------------------------------
    cli_complete = args.characters and (args.season_end or args.weeks)
    use_interactive = args.interactive or not cli_complete

    if use_interactive:
        if args.json:
            print(t(lang, 'json_requires_cli'), file=sys.stderr)
            sys.exit(1)
        config = interactive_inputs(lang)
        config['n_sims'] = args.sims
        config['seed'] = args.seed
    else:
        # CLI completo
        today = date.today()
        next_reset = next_tuesday(today)
        if args.weeks is not None:
            weeks = args.weeks
            season_end = next_reset + timedelta(days=7 * (weeks - 1))
        else:
            season_end = parse_date_flexible(args.season_end)
            weeks = weeks_remaining(next_reset, season_end)
        config = {
            'today': today,
            'next_reset': next_reset,
            'season_end': season_end,
            'weeks': weeks,
            'total': args.total,
            'characters': parse_characters(args.characters),
            'character_crests': parse_character_crests(args.crests),
            'character_maxxed': parse_character_maxxed(args.maxxed),
            'n_sims': args.sims,
            'seed': args.seed,
        }

    # ------ analisa cada personagem -------------------------------------------
    char_results = [
        analyze_character(name, k, config['weeks'], config['total'],
                           config['n_sims'], config['seed'],
                           config.get('character_crests', {}).get(name, 0),
                           config.get('character_maxxed', {}).get(name, 0))
        for name, k in config['characters']
    ]

    # ------ saida JSON --------------------------------------------------------
    if args.json:
        reset_dates = list_reset_dates(config['next_reset'], config['season_end'])
        output = {
            'config': {
                'today': config['today'].isoformat(),
                'next_reset': config['next_reset'].isoformat(),
                'season_end': config['season_end'].isoformat(),
                'weeks_remaining': config['weeks'],
                'total_items': config['total'],
                'n_simulations': config['n_sims'],
                'crest_rules': {
                    'crests_per_timed_12': CRESTS_PER_TIMED_12,
                    'crests_to_upgrade_item': CRESTS_TO_UPGRADE_ITEM,
                    'dungeons_by_s': DUNGEONS_BY_S,
                    'crests_by_s': CRESTS_BY_S,
                },
            },
            'reset_agenda': [d.isoformat() for d in reset_dates],
            'characters': char_results,
            'summary': _aggregated_summary(char_results, config['total']),
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # ------ saida humana ------------------------------------------------------
    print(f"\n{'=' * 70}")
    print(f"  {t(lang, 'report_title')}")
    print(f"  {t(lang, 'today')}: {config['today'].strftime('%d/%m/%Y (%A)')}")
    print(f"  {t(lang, 'next_reset')}: {config['next_reset'].strftime('%d/%m/%Y')}")
    print(f"  {t(lang, 'season_end_label')}: {config['season_end'].strftime('%d/%m/%Y')}")
    print(f"  {t(lang, 'header_summary', w=config['weeks'], t=config['total'], s=config['n_sims'])}")
    print(f"  {t(lang, 'crests_rule', per_run=CRESTS_PER_TIMED_12, per_item=CRESTS_TO_UPGRADE_ITEM)}")
    print(f"{'=' * 70}")

    reset_dates = list_reset_dates(config['next_reset'], config['season_end'])
    print(f"\n  {t(lang, 'reset_agenda', n=len(reset_dates))}:")
    for i, d in enumerate(reset_dates, 1):
        suffix = t(lang, 'last_marker') if i == len(reset_dates) else ""
        if i % 5 == 0 or i == len(reset_dates) or i == 1:
            print(f"    {i:2}. {d.strftime('%d/%m/%Y')}{suffix}")
        elif i == 2:
            print(f"    ...")

    for char in char_results:
        print_character_report(char, config['total'], lang)

    # ------ resumo agregado ---------------------------------------------------
    print(f"\n{'=' * 70}")
    print(f"  {t(lang, 'aggregated_summary', n=len(char_results))}")
    print(f"{'=' * 70}")
    summary = _aggregated_summary(char_results, config['total'])
    max_items = config['total'] * len(char_results)

    print(f"\n  {t(lang, 'strat_all_s2')}")
    print(f"    {t(lang, 'agg_time', min=summary['s2_time_min'], h=summary['s2_time_min']/60)}")
    print(f"    {t(lang, 'agg_items', n=summary['s2_items'], m=max_items, pct=100*summary['s2_items']/max_items)}")

    print(f"\n  {t(lang, 'strat_adaptive')}")
    print(f"    {t(lang, 'agg_time', min=summary['adaptive_time_min'], h=summary['adaptive_time_min']/60)}")
    print(f"    {t(lang, 'agg_items', n=summary['adaptive_items'], m=max_items, pct=100*summary['adaptive_items']/max_items)}")

    print(f"\n  {t(lang, 'strat_crest_aware')}")
    print(f"    {t(lang, 'agg_time', min=summary['crest_aware_time_min'], h=summary['crest_aware_time_min']/60)}")
    print(f"    {t(lang, 'agg_items_upgraded', n=summary['crest_aware_upgraded_items'], m=max_items, pct=100*summary['crest_aware_upgraded_items']/max_items)}")

    print(f"\n  {t(lang, 'strat_max_loot')}")
    print(f"    {t(lang, 'agg_dungeons', n=summary['max_loot_then_crests_dungeons'])}")
    print(f"    {t(lang, 'agg_time', min=summary['max_loot_then_crests_time_min'], h=summary['max_loot_then_crests_time_min']/60)}")
    print(f"    {t(lang, 'agg_looted', n=summary['max_loot_then_crests_looted_items'], m=max_items, pct=100*summary['max_loot_then_crests_looted_items']/max_items)}")
    print(f"    {t(lang, 'agg_items_upgraded', n=summary['max_loot_then_crests_upgraded_items'], m=max_items, pct=100*summary['max_loot_then_crests_upgraded_items']/max_items)}")

    print(f"\n  {t(lang, 'actions_for_week', date=config['next_reset'].strftime('%d/%m/%Y'))}:")
    for char in char_results:
        rec = char['recommendation_this_week']
        print(f"    {t(lang, 'action_line', name=char['name'], k=char['k_inicial'], s=rec['play_s'], min=rec['time_min'], c=rec['crests'], pct=rec['p_new_item'])}")
    total_week = sum(c['recommendation_this_week']['time_min'] for c in char_results)
    print(f"    {t(lang, 'total_label'):<15}: {t(lang, 'total_week_line', min=total_week, h=total_week/60)}")

    print(f"\n  {t(lang, 'actions_max_loot')}")
    for char in char_results:
        rec = char['max_loot_then_crests']
        print(f"    {t(lang, 'action_max_line', name=char['name'], k=char['k_inicial'], s=rec['action_this_week'], d=rec['dungeons_this_week'], min=rec['time_this_week_min'], c=rec['crests_this_week'])}")
    total_max_week = sum(c['max_loot_then_crests']['time_this_week_min'] for c in char_results)
    total_max_dungeons = sum(c['max_loot_then_crests']['dungeons_this_week'] for c in char_results)
    print(f"    {t(lang, 'total_label'):<15}: {t(lang, 'total_max_line', d=total_max_dungeons, min=total_max_week, h=total_max_week/60)}")
    print()


def _aggregated_summary(char_results: List[Dict], total: int) -> Dict:
    """Calcula totais agregados sobre todos personagens."""
    return {
        's2_time_min': sum(c['fixed']['s=2']['mean_time_min'] for c in char_results),
        's2_items': sum(c['fixed']['s=2']['mean_items_mc'] for c in char_results),
        'adaptive_time_min': sum(
            c['adaptive']['lambda=0.0005']['expected_time_min']
            for c in char_results),
        'adaptive_items': sum(
            c['adaptive']['lambda=0.0005']['expected_items']
            for c in char_results),
        'crest_aware_time_min': sum(
            c['crest_aware']['lambda=0.0005']['expected_time_min']
            for c in char_results),
        'crest_aware_upgraded_items': sum(
            c['crest_aware']['lambda=0.0005']['expected_upgraded_items']
            for c in char_results),
        'this_week_total_min': sum(
            c['recommendation_this_week']['time_min'] for c in char_results),
        'this_week_total_crests': sum(
            c['recommendation_this_week']['crests'] for c in char_results),
        'max_loot_then_crests_time_min': sum(
            c['max_loot_then_crests']['expected_time_min']
            for c in char_results),
        'max_loot_then_crests_dungeons': sum(
            c['max_loot_then_crests']['expected_dungeons']
            for c in char_results),
        'max_loot_then_crests_looted_items': sum(
            c['max_loot_then_crests']['expected_looted_items']
            for c in char_results),
        'max_loot_then_crests_upgraded_items': sum(
            c['max_loot_then_crests']['expected_upgraded_items']
            for c in char_results),
    }


if __name__ == '__main__':
    main()
