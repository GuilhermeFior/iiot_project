"""Controlador Fuzzy-PI incremental para a vazão de ácido.

O controlador usa sete termos linguísticos para erro e variação do erro.
As 49 combinações são agregadas pelo método de Mamdani e defuzzificadas pelo
centroide. A saída representa uma correção incremental na vazão de ácido.
"""

from __future__ import annotations

from dataclasses import dataclass


LINGUISTIC_LEVELS = (-3, -2, -1, 0, 1, 2, 3)


def clamp(value: float, lower: float, upper: float) -> float:
    """Limita ``value`` ao intervalo fechado informado."""
    return max(lower, min(upper, value))


def triangular_memberships(value: float) -> dict[int, float]:
    """Calcula pertinências triangulares uniformes para sete termos."""
    bounded_value = clamp(value, -3.0, 3.0)
    return {
        level: max(0.0, 1.0 - abs(bounded_value - level))
        for level in LINGUISTIC_LEVELS
    }


def consequent_level(error_level: int, delta_error_level: int) -> int:
    """Retorna o consequente de uma das 49 regras Fuzzy-PI.

    O erro tem maior peso; a derivada do erro reforça ou suaviza a ação.
    Assim, erro de pH positivo aumenta a vazão de ácido e erro negativo a
    reduz. A expressão gera uma base de regras simétrica e reproduzível.
    """
    return int(clamp(round(error_level + 0.35 * delta_error_level), -3, 3))


@dataclass(frozen=True)
class FuzzyPIConfig:
    """Parâmetros de escala do controlador."""

    error_scale_ph: float = 1.5
    delta_error_scale_ph_s: float = 0.25
    max_flow_adjustment_l_s: float = 0.08


class FuzzyPIController:
    """Controlador Mamdani com ação PI incremental."""

    def __init__(self, config: FuzzyPIConfig | None = None) -> None:
        self.config = config or FuzzyPIConfig()

    def compute(self, error_ph: float, delta_error_ph_s: float) -> float:
        """Calcula a correção de vazão de ácido em L/s."""
        normalized_error = clamp(error_ph / self.config.error_scale_ph, -3.0, 3.0)
        normalized_delta = clamp(
            delta_error_ph_s / self.config.delta_error_scale_ph_s, -3.0, 3.0
        )
        error_memberships = triangular_memberships(normalized_error)
        delta_memberships = triangular_memberships(normalized_delta)

        numerator = 0.0
        denominator = 0.0
        # Universo de saída discretizado para calcular o centroide.
        for index in range(-60, 61):
            output_value = index / 20
            activation = 0.0
            for error_level, error_membership in error_memberships.items():
                for delta_level, delta_membership in delta_memberships.items():
                    rule_activation = min(error_membership, delta_membership)
                    rule_output = consequent_level(error_level, delta_level)
                    output_membership = max(0.0, 1.0 - abs(output_value - rule_output))
                    activation = max(activation, min(rule_activation, output_membership))
            numerator += output_value * activation
            denominator += activation

        normalized_adjustment = numerator / denominator if denominator else 0.0
        return normalized_adjustment / 3.0 * self.config.max_flow_adjustment_l_s
