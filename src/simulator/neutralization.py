"""Modelo dinâmico simplificado de neutralização de pH em tanque agitado."""

from __future__ import annotations

from dataclasses import dataclass
from math import asinh

from .fuzzy_pi import FuzzyPIController, clamp


@dataclass(frozen=True)
class NeutralizationConfig:
    """Parâmetros físicos e operacionais do processo simulado.

    As concentrações representam equivalentes ácido-base. Os valores foram
    escolhidos para gerar uma planta estável e didática; devem ser calibrados
    com dados experimentais em uma etapa posterior do trabalho.
    """

    tank_volume_l: float = 1_000.0
    initial_acid_flow_l_s: float = 2.0
    min_acid_flow_l_s: float = 0.0
    max_acid_flow_l_s: float = 4.0
    nominal_effluent_flow_l_s: float = 10.0
    base_equivalent_mol_l: float = 0.02
    acid_equivalent_mol_l: float = 0.10
    buffer_capacity_mol_l: float = 0.005
    setpoint_ph: float = 7.0
    temperature_c: float = 25.0
    level_m: float = 1.2
    disturbance_start_s: float | None = None
    disturbance_duration_s: float = 20.0
    disturbance_flow_increment_l_s: float = 1.5


@dataclass(frozen=True)
class ProcessSnapshot:
    """Estado observável da planta após uma iteração de simulação."""

    time_s: float
    ph: float
    effluent_flow_l_s: float
    acid_flow_l_s: float
    temperature_c: float
    level_m: float
    valve_position_pct: float
    setpoint_ph: float
    error_ph: float
    delta_error_ph: float
    anomaly_label: bool
    anomaly_type: str | None


class NeutralizationSimulator:
    """Simula a neutralização e aplica um controlador Fuzzy-PI à vazão ácida."""

    def __init__(
        self,
        config: NeutralizationConfig | None = None,
        controller: FuzzyPIController | None = None,
    ) -> None:
        self.config = config or NeutralizationConfig()
        self.controller = controller or FuzzyPIController()
        self._time_s = 0.0
        self._excess_equivalents_mol = 0.0
        self._acid_flow_l_s = self.config.initial_acid_flow_l_s
        self._previous_error_ph = 0.0

    def _ph_from_excess(self) -> float:
        concentration = self._excess_equivalents_mol / self.config.tank_volume_l
        ph = self.config.setpoint_ph + 2.0 * asinh(
            concentration / self.config.buffer_capacity_mol_l
        )
        return clamp(ph, 0.0, 14.0)

    def _disturbance_is_active(self) -> bool:
        start = self.config.disturbance_start_s
        return (
            start is not None
            and start <= self._time_s < start + self.config.disturbance_duration_s
        )

    def step(self, time_step_s: float = 1.0) -> ProcessSnapshot:
        """Avança a planta em ``time_step_s`` segundos e retorna sua telemetria."""
        if time_step_s <= 0:
            raise ValueError("time_step_s deve ser maior que zero")

        ph_before_control = self._ph_from_excess()
        error_before_control = ph_before_control - self.config.setpoint_ph
        delta_error_ph_s = (
            error_before_control - self._previous_error_ph
        ) / time_step_s
        acid_adjustment = self.controller.compute(
            error_before_control, delta_error_ph_s
        )
        self._acid_flow_l_s = clamp(
            self._acid_flow_l_s + acid_adjustment,
            self.config.min_acid_flow_l_s,
            self.config.max_acid_flow_l_s,
        )

        disturbance_active = self._disturbance_is_active()
        effluent_flow_l_s = self.config.nominal_effluent_flow_l_s
        if disturbance_active:
            effluent_flow_l_s += self.config.disturbance_flow_increment_l_s

        # Balanço de equivalentes em um tanque perfeitamente misturado.
        net_input_mol_s = (
            effluent_flow_l_s * self.config.base_equivalent_mol_l
            - self._acid_flow_l_s * self.config.acid_equivalent_mol_l
        )
        outlet_equivalent_mol_s = (
            effluent_flow_l_s + self._acid_flow_l_s
        ) * self._excess_equivalents_mol / self.config.tank_volume_l
        self._excess_equivalents_mol += (
            net_input_mol_s - outlet_equivalent_mol_s
        ) * time_step_s
        self._time_s += time_step_s

        ph = self._ph_from_excess()
        error_ph = ph - self.config.setpoint_ph
        delta_error_ph = error_ph - self._previous_error_ph
        self._previous_error_ph = error_ph
        return ProcessSnapshot(
            time_s=self._time_s,
            ph=ph,
            effluent_flow_l_s=effluent_flow_l_s,
            acid_flow_l_s=self._acid_flow_l_s,
            temperature_c=self.config.temperature_c,
            level_m=self.config.level_m,
            valve_position_pct=(
                self._acid_flow_l_s / self.config.max_acid_flow_l_s * 100.0
            ),
            setpoint_ph=self.config.setpoint_ph,
            error_ph=error_ph,
            delta_error_ph=delta_error_ph,
            anomaly_label=disturbance_active,
            anomaly_type=("process_disturbance" if disturbance_active else None),
        )
