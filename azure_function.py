"""
Azure Function HTTP trigger - WoW Vault Recommender
Endpoint: POST /api/vault-recommend
Body JSON: { "k": 5, "weeks_left": 17, "lambda_cost": 0.0005 }
Response:  { "recommended_s": 2, "expected_items": ..., "expected_time_min": ..., ... }

Stack: Python 3.11, Azure Functions Core Tools v4
Deploy: func azure functionapp publish <NOME_DO_APP>
"""

import json
import logging
from typing import Dict

import azure.functions as func
import numpy as np

# importa as funcoes do simulador (deploy junto no mesmo diretorio)
from simulator import (
    solve_optimal_policy,
    markov_stats,
    pareto_frontier_markov,
    filter_pareto,
    COSTS,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


# ============================================================================
# Endpoint principal: dada situacao atual, retorna acao recomendada da semana
# ============================================================================
@app.route(route="vault-recommend", methods=["POST"])
def vault_recommend(req: func.HttpRequest) -> func.HttpResponse:
    """
    Recebe k atual e weeks_left, retorna estrategia recomendada.
    Para uso semanal em n8n: agendar para rodar toda terca apos reset.
    """
    try:
        body = req.get_json()
        k = int(body.get('k', 0))
        weeks_left = int(body.get('weeks_left', 22))
        total = int(body.get('total', 18))
        lambda_cost = float(body.get('lambda_cost', 0.0005))

        # validacao basica
        if not (0 <= k <= total):
            return func.HttpResponse(
                json.dumps({"error": "k fora do intervalo valido"}),
                status_code=400, mimetype="application/json"
            )
        if weeks_left < 1:
            return func.HttpResponse(
                json.dumps({"error": "weeks_left deve ser >= 1"}),
                status_code=400, mimetype="application/json"
            )

        # resolve politica otima e extrai acao do estado atual
        policy, V = solve_optimal_policy(lambda_cost, weeks_left, total)
        recommended_s = int(policy[k, weeks_left])

        # estatisticas projetadas da estrategia adaptativa
        # (aproximacao: assume que continuara seguindo a politica)
        # rodamos a propagacao de Markov com a politica adaptativa
        e_items_adaptive, time_adaptive = _project_adaptive(policy, weeks_left, total, k)

        # tambem entrega comparacao com estrategias fixas
        comparison = {}
        for s in [1, 2, 3]:
            e, p = markov_stats(s, weeks_left, total, k)
            comparison[f's={s}'] = {
                'expected_items': round(e, 2),
                'p_complete': round(p, 4),
                'time_min': weeks_left * COSTS[s],
            }

        response = {
            'inputs': {'k': k, 'weeks_left': weeks_left,
                        'total': total, 'lambda_cost': lambda_cost},
            'recommendation': {
                'play_s': recommended_s,
                'time_this_week_min': COSTS[recommended_s],
                'p_new_this_week': round(1 - (k / total) ** recommended_s, 3) if recommended_s > 0 else 0.0,
            },
            'projection_end_of_season': {
                'expected_final_items': round(e_items_adaptive, 2),
                'expected_total_time_min': round(time_adaptive, 1),
                'pct_completion': round(100 * e_items_adaptive / total, 1),
            },
            'comparison_fixed_strategies': comparison,
        }

        return func.HttpResponse(
            json.dumps(response, ensure_ascii=False, indent=2),
            status_code=200, mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"Erro: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500, mimetype="application/json"
        )


# ============================================================================
# Funcao auxiliar: projeta E[itens] e E[tempo] seguindo politica adaptativa
# ============================================================================
def _project_adaptive(policy: np.ndarray, weeks: int, total: int,
                       k_inicial: int) -> tuple:
    """Propaga distribuicao de k seguindo policy[k, w] e calcula esperanca."""
    P = np.zeros(total + 1)
    P[k_inicial] = 1.0
    expected_time = 0.0
    for week_idx in range(weeks):
        weeks_remaining = weeks - week_idx
        new_P = np.zeros(total + 1)
        for k in range(total + 1):
            if P[k] == 0:
                continue
            s = int(policy[k, weeks_remaining])
            expected_time += P[k] * COSTS[s]
            p = 1 - (k / total) ** s if s > 0 else 0
            new_P[k] += P[k] * (1 - p)
            if k < total:
                new_P[k + 1] += P[k] * p
        P = new_P
    expected_items = float(np.sum(np.arange(total + 1) * P))
    return expected_items, expected_time
