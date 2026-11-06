# Where EnergyPlus 26.2.0 uses the previous timestep's zone air temperature

This is the source trace behind the paper's account of the order of calculation (its Appendix A).

- Source: EnergyPlus tag `v26.2.0`, commit `4bd7a1f26fb749a83257855aba6760e26c8a3c8f`, the build
  hash that the released 26.2.0 programs print (`energyplus --version`). The links point to that
  commit, so the line numbers do not drift.
- Documentation: the 26.2.0 Engineering Reference (ER) and Input Output Reference (IOR)
  distributed with the release.

## The order of calculation within a zone timestep

For zones with the standard well-mixed air model:

1. The outside surface heat balances are solved. For "quick-conducting" surfaces (CTF cross term
   above 0.01, which includes massless layers), this solution includes the inside face, using the
   zone mean air temperature `MAT`.
2. The inside surface heat balances are solved. Their reference air temperature is `MAT`, and the
   interior convection coefficients are also computed with `MAT`. Their iteration solves the
   surfaces against each other with the air temperature held fixed.
3. The zone air balance is solved (predictor, HVAC, corrector) with the surface temperatures from
   step 2. `MAT` is updated only here.
4. The surfaces are not solved again with the updated air temperature, unless a radiant system,
   baseboard, cooling panel, swimming pool or surface-coupled PV is active. Then the surfaces are
   solved once more with the new air temperature, and the air is not solved again.

The surfaces of step $t$ therefore see the air temperature at the end of step $t-\delta t$, while
the air of step $t$ sees the surfaces of step $t$. The patches in `patches/` add passes that repeat
steps 1 to 3 within the timestep until the two agree.

## Locations in the source

| # | What | Where | What it shows |
|---|---|---|---|
| 1 | Timestep loop | `SimulationManager.cc` [L569–L612](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/SimulationManager.cc#L569-L612) | For each zone timestep: `ManageWeather`, then `ManageHeatBalance`. |
| 2 | Heat balance entry | `HeatBalanceManager.cc` [L211](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceManager.cc#L211) | `ManageHeatBalance` calls `ManageSurfaceHeatBalance` once per zone timestep. |
| 3 | Order of solves | `HeatBalanceSurfaceManager.cc` [L184](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L184), [L188](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L188), [L195](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L195), [L200](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L200), [L204](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L204) | Outside surfaces, inside surfaces, air balance, final surface update, then history update. |
| 4 | Air balance calls HVAC | `HeatBalanceAirManager.cc` [L161](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceAirManager.cc#L161), [L4637](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceAirManager.cc#L4637) | `ManageAirHeatBalance` → `CalcHeatBalanceAir` → `HVACManager::ManageHVAC`. |
| 5 | Predictor, HVAC, corrector | `HVACManager.cc` [L265–L305](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HVACManager.cc#L265-L305), sub-step loop [L333–L385](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HVACManager.cc#L333-L385) | Predict step, `SimHVAC`, correct step, and the same within each HVAC sub-step. No surface heat balance is called anywhere in `ManageHVAC` (L132–L689). |
| 6 | Where `MAT` is set | `ZoneTempPredictorCorrector.cc` [L4175](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/ZoneTempPredictorCorrector.cc#L4175), [L6850](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/ZoneTempPredictorCorrector.cc#L6850) | `MAT = ZT` at the end of `correctAirTemp` (the corrector). The only other assignment resets `MAT` from interpolated history when HVAC changes its sub-step count. Both run inside `ManageHVAC`, after the surfaces are solved. |
| 7 | Inside surfaces read `MAT` | `HeatBalanceSurfaceManager.cc` [L8186](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L8186) and [L9045](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L9045); `DataSurfaces.cc` `getInsideAirTemperature` | Both inside solvers (general and CTF-only) set each surface's reference air temperature from `getInsideAirTemperature` before their iteration loop. That function returns `MAT` for the zone-mean reference and for the default case. Every surface reference starts as `Invalid` ([SurfaceGeometry.cc L923](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/SurfaceGeometry.cc#L923)), which falls to that default. |
| 8 | Air held fixed in the inside loop | `HeatBalanceSurfaceManager.cc` loops from [L8231](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L8231) and [L9113](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L9113) | Inside the loops, `MAT` and the stored reference temperature are only read. No air temperature is assigned. |
| 9 | Convection coefficients use `MAT` | `ConvectionCoefficients.cc` `InitIntConvCoeff` [L291](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/ConvectionCoefficients.cc#L291), used at [L333](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/ConvectionCoefficients.cc#L333) (TARP, `HcInt::ASHRAETARP`) and others; adaptive equations at [L3221](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/ConvectionCoefficients.cc#L3221) | The interior convection coefficients are evaluated with the previous step's `MAT`. |
| 10 | Outside surfaces read `MAT` | `HeatBalanceSurfaceManager.cc` `CalcOutsideSurfTemp`, criterion [L9808–L9821](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L9808-L9821), uses at [L9936](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L9936), [L9950](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L9950), [L9970](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L9970), [L9979](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L9979) | For quick-conducting surfaces the outside solve includes $h_{in}\cdot$`MAT`. The code comment says the quick/slow distinction is "inherited from BLAST" and that a slow surface "can used the last time step's value for inside surface temperature". |
| 11 | Air uses current surfaces | `ZoneTempPredictorCorrector.cc` [L5333–L5336](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/ZoneTempPredictorCorrector.cc#L5333-L5336); `DataHeatBalance.cc` [L131](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/DataHeatBalance.cc#L131) | The corrector's surface convection sum uses `SurfTempInTmp`, the inside temperatures just set by step 2. |
| 12 | When surfaces are re-solved | `HeatBalanceSurfaceManager.cc` [L5466–L5471](https://github.com/NatLabRockies/EnergyPlus/blob/4bd7a1f26fb749a83257855aba6760e26c8a3c8f/src/EnergyPlus/HeatBalanceSurfaceManager.cc#L5466-L5471) | `UpdateFinalSurfaceHeatBalance` re-solves outside and inside surfaces only if a low- or high-temperature radiant system, a hot-water, steam or electric baseboard, a cooling panel, a pool, or surface-coupled PV is active. The radiant and baseboard modules also call the inside solver during their own simulation. Forced-air systems trigger none of these. |

## What the documentation says

- ER p. 30, deriving the update formula: the remaining terms "are not known at the current time,
  they were lagged by one time step".
- ER p. 31: the third-order scheme "requires zone air temperatures at three previous time steps"
  and assumes "three previous time steps lengths are the same".
- ER pp. 31–33: the predictor–corrector. The load is predicted at the setpoint, the system is
  simulated, and the zone temperature is corrected.
- IOR p. 46: "Shorter zone timesteps improve the numerical solution of the Zone Heat Balance Model
  because they improve how models for surface temperature and zone air temperature are coupled
  together. Longer timesteps introduce more lag."
- The inside surface chapter of the ER (pp. 109–132) does not say which timestep's air temperature
  enters the inside balance. The lag of quick-conducting surfaces in the outside balance (row 10)
  is described only in a code comment.

## Limits of the trace

- RoomAir models (displacement, cross ventilation, underfloor air distribution) use a per-surface
  adjacent air temperature (`AdjacentAirTemp`). They were not examined.
- The CeilingDiffuser interior convection model uses the supply air temperature from the zone
  inlet nodes when there is flow (the last HVAC solution), and `MAT` when there is none.
- The systems listed in row 12 solve the surfaces once more with the new air temperature. The air
  is still not solved again.
- HVAC sub-steps update `MAT` within the zone timestep, but the surfaces stay fixed through all
  sub-steps (row 5).

## Earlier releases

`HeatBalanceSurfaceManager.cc` at tags v8.2.0 (2014, the first C++ release), v9.0.0, v22.1.0 and
v24.1.0 has the same order within a zone timestep (`CalcHeatBalanceOutsideSurf`,
`CalcHeatBalanceInsideSurf`, `ManageAirHeatBalance`), and the inside surfaces take the zone mean
air temperature `MAT` of the previous timestep: `RefAirTemp(SurfNum) = MAT(ZoneNum)` at v8.2.0
(line 5126) and v9.0.0 (line 6023), and `getInsideAirTemperature` at v22.1.0 (line 6924) and
v24.1.0 (line 7639). Earlier releases were written in Fortran. For them, Strand et al. (2001)
describe the loop taken over from BLAST (surfaces iterated, air solved after the loop) as kept
"substantially the same" in EnergyPlus.

## How to check

```bash
git clone --depth 1 --branch v26.2.0 --filter=blob:none --sparse https://github.com/NatLabRockies/EnergyPlus.git
cd EnergyPlus && git sparse-checkout set src/EnergyPlus && git rev-parse HEAD   # 4bd7a1f26f...
grep -n "this->MAT = " src/EnergyPlus/ZoneTempPredictorCorrector.cc
grep -n "getInsideAirTemperature(state" src/EnergyPlus/HeatBalanceSurfaceManager.cc
grep -n "spaceHeatBalance(spaceNum).MAT" src/EnergyPlus/HeatBalanceSurfaceManager.cc
```

Reference: Strand, R. K., C. O. Pedersen and D. B. Crawley. 2001. "Modularization and simulation
techniques for heat balance based energy and load calculation programs: the experience of the
ASHRAE Loads Toolkit and EnergyPlus." In Proceedings of Building Simulation 2001, 43–50.
International Building Performance Simulation Association.
