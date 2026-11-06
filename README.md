# Surface–air coupling passes for EnergyPlus 26.2.0

Research patches and scripts for EnergyPlus version 26.2.0. This repository is not affiliated with
or endorsed by the U.S. Department of Energy or the EnergyPlus development team. EnergyPlus™ is a
trademark of the U.S. Department of Energy.

The repository accompanies the paper

> Jung, W. "The one-step surface–air lag in the EnergyPlus zone heat balance: order of accuracy,
> correction and consequences." Preprint: arXiv (identifier to be added).

In each zone timestep, EnergyPlus solves the surface heat balances with the zone air temperature of
the previous timestep, then the zone air balance with the new surface temperatures, and does not go
back. The patches add optional passes that solve the surfaces, the air and the HVAC again within the
timestep until they agree. The repository holds the patches, the scripts that run every test of
the paper, and the summary results behind each of its numbers, tables and figures.

## Contents

| Folder | Contents |
|---|---|
| `patches/` | Five patches against EnergyPlus v26.2.0 (commit 4bd7a1f26f), applied in order |
| `build/` | Install the release, build the patched program, check that it reproduces the release |
| `configurations.py` | The program configurations of the paper and the variables that switch the passes |
| `tests/` | Tests on simple models: massive wall, single room, room with an exact solution, and checks on the passes |
| `study/` | The prototype study: 16 DOE prototype buildings in three climates |
| `paper/` | Scripts that build the paper's tables and figures from `results/`, and their output |
| `results/` | Summary results (CSV) behind every number of the paper |
| `docs/` | Source trace of the order of calculation; outcome measures and thresholds set before the prototype runs |
| `weather/` | The Denver weather file of the tests |

Raw EnergyPlus output goes to `runs/` (not tracked, several GB for the prototype study).

## The patched program

With no variable set, the patched program computes exactly what the release computes. The passes
are switched on through environment variables:

| Variable | Meaning | Default |
|---|---|---|
| `SURFACE_AIR_PASSES` | maximum extra passes per zone timestep | 0 (off) |
| `SURFACE_AIR_TOL` | stop when no zone air temperature changes by more than this between passes [°C] | 1e-9 |
| `SURFACE_AIR_OUTSIDE` | 1 = each pass also solves the outside surface heat balance again | 0 |
| `SURFACE_AIR_HVAC` | 1 = each pass also repeats the load prediction and the HVAC simulation | 0 |
| `SURFACE_AIR_LOG` | 1 = report each zone timestep that ends at the pass limit | 0 |
| `INSIDE_SURFACE_TOL` | inside surface convergence tolerance [°C], also below the input minimum | 0.002 |

The paper's configurations (`configurations.py`):

| Configuration | Program and settings |
|---|---|
| `release` | EnergyPlus 26.2.0 as distributed |
| `one_pass` | patched; `SURFACE_AIR_PASSES=1`, `SURFACE_AIR_OUTSIDE=1`, `SURFACE_AIR_HVAC=1` |
| `two_passes` | patched; as `one_pass` with `SURFACE_AIR_PASSES=2` (the correction examined for practical use) |
| `converged` | patched; up to 50 passes to 1e-9 °C, both faces and HVAC, `INSIDE_SURFACE_TOL=1e-8` (the reference) |

The tests on simple models also use `passes_off` (patched, nothing set), `inside_faces` and
`both_faces` (solved to agreement with only the inside faces, or both faces, solved again, and the
HVAC held at its first result).

Each run writes the pass statistics of each environment to `eplusout.err`, for example
`Surface-air passes: RUNPERIOD 1: 52560 timesteps, mean extra passes 2.00, max 2, not converged
52560`. "Not converged" counts the timesteps that ended at the pass limit, so with a fixed number of
passes it equals the number of timesteps.

## Requirements

- Linux (the paper used Ubuntu 24.04 on x86_64), git, cmake 3.20 or later and a C++ compiler (the
  paper used GCC 13.3). gfortran is optional.
- Python 3.10 or later with the packages in `requirements.txt`.
- Disk: the source build and the raw runs of the prototype study take several gigabytes.
- Time: the prototype study is about 850 annual runs of the prototype buildings, run in parallel,
  and its runtime test adds 189 runs executed one at a time (about 12 hours in the paper). The
  tests on simple models are mostly short runs of one zone.

## Reproducing the results

All commands run from the repository root. Install folders default to `~/EnergyPlus/…`; set
`ENERGYPLUS_RELEASE`, `ENERGYPLUS_PATCHED` and `ENERGYPLUS_PROTOTYPES` to use others.

```bash
pip install -r requirements.txt

# 1. Programs
build/install_release.sh                          # release 26.2.0, checksum-verified
build/build_patched.sh                            # clone v26.2.0, apply patches/, compile
python3 build/compare_programs.py --test passes_off   # must report 0 differing values

# 2. Tests on simple models (results/massive_wall, single_room, exact_room, order_estimates, passes)
python3 tests/massive_wall.py
python3 tests/single_room.py --configurations release both_faces converged
python3 tests/single_room_orders.py
python3 tests/hvac_held_fixed.py
python3 tests/room_variants.py
python3 tests/control_patterns.py
python3 tests/constant_setpoint.py
python3 tests/exact_room.py
python3 tests/exact_room_schemes.py
python3 tests/exact_room_updates.py
python3 tests/lag_heat_capacity.py
python3 tests/order_estimates.py
python3 tests/pass_limits.py
tests/pass_runtime.sh                              # on an otherwise idle machine

# 3. Prototype study (results/prototypes). Download the 16 prototype zips and three weather
#    files first: prepare_inputs.py lists the URLs and checks every file's SHA-256.
python3 study/prepare_inputs.py
study/check_sizing_passes.sh
python3 study/run_cases.py
python3 study/analyze_cases.py
python3 study/describe_cases.py
python3 study/direction_tests.py
python3 study/savings_spread.py
python3 study/locate_changes.py
python3 study/savings_timestep.py run && python3 study/savings_timestep.py analyze
python3 study/pass_limit_share.py
python3 tests/energy_balance.py                    # needs the release runs of run_cases.py
python3 study/accuracy_runtime.py reference
python3 study/accuracy_runtime.py timed            # one run at a time, on an idle machine
python3 study/accuracy_runtime.py analyze
python3 study/accuracy_fixed_sizes.py prepare && python3 study/accuracy_fixed_sizes.py run \
  && python3 study/accuracy_fixed_sizes.py analyze

# 4. Paper tables and figures (from results/ only, no simulation)
python3 paper/make_result_tables.py
python3 paper/make_case_tables.py
python3 paper/make_figures.py
python3 paper/make_schematics.py
```

Every Python script prints its options with `--help`, and most accept subsets (`--configurations`,
`--cases`, `--timesteps`) so that part of the work can be checked without rerunning everything.
Results on other machines can differ from the published files by floating-point amounts (about
1e-9 °C in temperatures, 0.01 GJ in annual totals) and in warning counts. Runtimes depend on the
machine.

## Where the paper's results come from

| Paper | Results | Script |
|---|---|---|
| Methods: the patched program reproduces the release | `results/release_check/` | `build/compare_programs.py` |
| Methods: passes active during sizing, sizes unchanged with passes off | `results/prototypes/sizing_passes_check.txt` | `study/check_sizing_passes.sh` |
| Methods: energy balance of the zone air and fan meter with the passes on | `results/passes/energy_balance*.csv` | `tests/energy_balance.py` |
| Methods: outcome measures and thresholds | `docs/analysis_plan.md` | – |
| Order of the release, single room; Figure 3 | `results/single_room/release/`, `observed_order_ref30.csv`, `rms_error_ts04_ref30.csv`, `results/order_estimates/` | `tests/single_room.py`, `single_room_orders.py`, `order_estimates.py` |
| Massive wall | `results/massive_wall/` | `tests/massive_wall.py` |
| Room with an exact solution; Figure 4 | `results/exact_room/` | `tests/exact_room.py`, `exact_room_schemes.py`, `exact_room_updates.py`, `lag_heat_capacity.py` |
| Solving the balances to agreement, single room; Table 3 | `results/single_room/converged/`, `room_variants.csv`, `results/order_estimates/` | `tests/single_room.py`, `room_variants.py`, `order_estimates.py` |
| Controlled zones, HVAC held fixed or in the passes, daily cycle | `results/single_room/hvac_held_fixed.csv`, `control_patterns.csv`, `constant_setpoint.csv` | `tests/hvac_held_fixed.py`, `control_patterns.py`, `constant_setpoint.py` |
| Limits on the passes and their runtime; Table 4 | `results/passes/pass_limits_*.csv` | `tests/pass_limits.py` |
| Prototype outcomes; Table 5, Figure 5, per-case tables | `results/prototypes/case_metrics.csv`, `case_deltas.csv`, `outcome_counts.csv` | `study/run_cases.py`, `analyze_cases.py` |
| Pass limit of the converged configuration | `results/prototypes/converged_pass_limit.csv`, `pass_limit_share.csv` | `study/describe_cases.py`, `pass_limit_share.py` |
| Where the largest changes occur | `results/prototypes/largest_changes*.csv` | `study/locate_changes.py` |
| Window savings; Figure 6 | `results/prototypes/case_deltas.csv`, `window_savings_spread.csv`, `window_savings_timestep*.csv` | `study/analyze_cases.py`, `savings_spread.py`, `savings_timestep.py` |
| Consistent direction, thresholds halved and doubled | `results/prototypes/direction_tests.csv`, `paper/tables/tab_robust.tex` | `study/direction_tests.py`, `paper/make_result_tables.py` |
| Accuracy against runtime; Figure 7 | `results/prototypes/accuracy_runtime_*.csv` | `study/accuracy_runtime.py` |
| Accuracy with fixed equipment sizes | `results/prototypes/accuracy_fixed_sizes*.csv` | `study/accuracy_fixed_sizes.py` |
| Appendix A: source locations | `docs/source_trace.md` | – |

Inputs: the tests build their input files from `1ZoneUncontrolled.idf` and the small office in the
`ExampleFiles` of the release, so no input file is stored here. The prototype study uses the ASHRAE
90.1-2019 prototype models of the U.S. Department of Energy from
https://www.energycodes.gov/prototype-building-models, which are not redistributed here;
`results/prototypes/sources.csv` and `weather.csv` give the SHA-256 of every file used.

## Licenses

- `patches/`: modifications of EnergyPlus, under the EnergyPlus license
  (`patches/LICENSE-EnergyPlus.txt`), which applies to the modified source.
- Scripts (`build/`, `tests/`, `study/`, `paper/`, `configurations.py`): BSD 3-Clause (`LICENSE`).
- `results/`, `docs/` and the generated tables and figures in `paper/`: Creative Commons
  Attribution 4.0 International (CC BY 4.0, `results/LICENSE.md`).

## Citation

Please cite the paper and the archived version of this repository (Zenodo DOI to be added). See
`CITATION.cff`.
