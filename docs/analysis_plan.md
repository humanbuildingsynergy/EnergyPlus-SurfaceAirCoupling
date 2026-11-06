# Outcome measures and thresholds of the prototype study

The measures, thresholds and decision rules below were fixed in a dated record on 4 November 2026
at 13:50 MST, before any run of the prototype study. The record is a tagged commit
(`50dbcf2`) in the author's research repository. This file restates its content in the terms of
the paper and of this repository. The amendments at the end were recorded later the same day,
each before the results it concerns were seen. The paper's hypothesis H3 consists of the five
outcomes in section 3 and the runtime test in section 5.

## 1. Question

Does removing the one-step surface–air lag, with the HVAC solved again in each pass, change results
that EnergyPlus users and code compliance rely on, in public reference models, and at what
runtime cost?

## 2. Configurations and models

- Configurations (`configurations.py`): the release of EnergyPlus 26.2.0 as distributed, one pass,
  two passes and converged. Two passes is the primary configuration. One pass and converged are
  reported alongside.
- Models: the 16 commercial prototype buildings of the U.S. Department of Energy in their
  ASHRAE 90.1-2019 versions, from energycodes.gov, in Miami (1A), Denver (5B) and International
  Falls (7), with the TMY3 weather files distributed with the prototypes and the design days of
  each file. 48 cases.
- Each file is converted to EnergyPlus 26.2 with the transition programs of the release, and
  every transition warning is kept. Nothing else is changed, except a full-year run period (if
  not already set), SQLite output, and the window upgrade.
- Timestep and all other settings as distributed, with autosizing.
- A case in which the release ends in a fatal error is excluded and listed. A case in which the
  release runs and two passes fail is a result and is reported.

Checks before the study runs: the patched program with the passes off reproduces the release
(`build/compare_programs.py`), and the passes are active during the sizing design days
(`study/check_sizing_passes.sh`).

## 3. Outcomes and the change that counts as material

Each case compares the release with two passes at the timestep of the file.

| Outcome | Material change |
|---|---|
| Annual heating, cooling or fan energy | at least 1% of that end use |
| Annual peak electric demand | at least 2% |
| Occupied unmet heating and cooling hours | at least 10% of the release value and at least 5 h, or the release and two passes on opposite sides of 300 h |
| Autosized capacities summed per building (cooling coils, heating coils, supply fan flow) | at least 2% |
| Savings of a window upgrade | a relative change of at least 10%, or a change of sign |

- End uses below 5% of the case's total site energy are reported but do not count.
- An outcome is judged to matter in practice when the threshold is met in at least 25% of the
  eligible cases.
- Window upgrade: every `WindowMaterial:SimpleGlazingSystem` set to U = 1.42 W/(m² K) and
  SHGC = 0.25 where both shipped values are higher. Cases with no such glazing are excluded from
  this outcome and listed.
- Reasons for the thresholds: 1% of an end use is the size of many single measures in these
  models. Sizes and peaks are rounded and include safety factors, so 2% is used. Unmet hours are
  small whole numbers, so they have both a relative and an absolute bar.

## 4. Reporting

- Every case is reported, in per-case tables and as distributions in the text.
- For the three cases with the largest change in an eligible end use: which zones and which hours
  carry the change.
- Every case with timesteps at the pass limit of the converged configuration is flagged.
- No outcome, threshold or case is added or dropped after results are seen, except through a
  dated amendment.

## 5. Accuracy against runtime

- Medium office, primary school, standalone retail and small office in Denver, at 4, 6, 10, 15,
  20, 30 and 60 timesteps per hour, with the release, one pass and two passes.
- Reference: the converged configuration at 60 timesteps per hour, with its run at 30 as a check.
- Errors: relative error of annual heating and of annual cooling energy, and the RMS error of
  hourly mean air temperature over the conditioned zones.
- Runtime: wall time, runs executed one at a time, three repeats, median reported.
- The coupled solution counts as faster when, in at least 3 of the 4 buildings, the release needs
  at least twice the runtime of two passes at 4 timesteps per hour to reach the same error
  (interpolated on logarithmic scales across timesteps).

## 6. Amendments (4 November 2026)

1. **Disclosure, no change.** Six minutes before the record was made, an exploratory run of the
   16 Denver prototypes shipped with the release was started. It was stopped nine minutes later,
   before it wrote or printed any result. Its outputs were deleted unread, and its script was not
   kept.
2. **Implementation details, fixed before any study run.** They make sections 2 to 5 concrete
   without changing them.
   - Sources: the 16 `ASHRAE901_<building>_STD2019.zip` files and the three TMY3 files from the
     energycodes.gov prototype page, with checksums in `results/prototypes/sources.csv` and
     `weather.csv`. All three cities are in the set, so no city was substituted.
   - The files are EnergyPlus 22.1, converted one version at a time with no severe error. The run
     period is already the full year and the timestep six per hour in all 48. The only addition is
     `Output:SQLite, SimpleAndTabular;`.
   - Window upgrade: applied per `WindowMaterial:SimpleGlazingSystem` object where both 1.42 and
     0.25 are below the shipped values. A case is eligible when at least one object is upgraded:
     36 cases, 12 excluded. Savings are the total site energy of the base run minus that of the
     upgraded run, per configuration.
   - Energy: heating = End Uses table, Heating, electricity + natural gas; cooling = Cooling,
     electricity + natural gas; fans = Fans, electricity; total = Total Site Energy. A case is
     material when any of its eligible end uses (at least 5% of the release's total) meets the
     threshold. Eligible cases have at least one eligible end use.
   - Unmet hours: the 10% and 5 h test applies to heating and to cooling separately, the 300 h
     test to their sum, as the performance rating method applies its limit to the total. Material
     when any of the three holds.
   - Capacities: from the Component Sizing Information lines of the `.eio` file, "Design Size"
     values only, and none for a component and quantity that also has a "User-Specified" value.
     Per component the largest matching value counts once (multi-speed coils report one value per
     speed). Cooling: `Coil:Cooling:*`, total cooling capacity or design coil load [W]. Heating:
     `Coil:Heating:*`, capacity [W]. Supply fan flow: `Fan:*` except `Fan:ZoneExhaust`, maximum
     flow rate [m³/s]. Material when any sum with a nonzero release value changes by at least 2%.
   - A case in which two passes fail cannot enter the count of eligible cases, which holds cases
     where both the release and the configuration completed.
   - The study runs execute in parallel, and their wall times are not used.
   - Accuracy against runtime: each input is changed only in its timestep and by an hourly output
     of Zone Mean Air Temperature. Conditioned zones are those named by a `ZoneControl:Thermostat`,
     directly or through a zone list. RMS over all hours of the year. In the timed runs the
     repeats are the outer loop. The primary error is the hourly air temperature, the quantity the
     lag acts on directly. The release's runtime to reach the error of two passes at 4 per hour is
     interpolated on logarithmic scales along the release's timesteps (first crossing). If the
     release does not reach it at 60 per hour, the ratio of the release at 60 per hour to two
     passes at 4 per hour is reported as a lower bound and counts as met when it is at least 2.
3. **Exclusions, recorded when all release runs had finished and before any outcome was
   computed.**
   - The small office is excluded in all three climates. The release ends in a fatal error in all
     three (base and upgraded inputs), and so does every patched configuration: "Potential Node
     Connection Error for object WATERHEATER:MIXED, name=SWHSYS1 WATER HEATER … Node Types are
     still UNDEFINED". The cause is in the energycodes.gov 22.1 file, not in the conversion: the
     water heater is a component on a plant branch, but its use-side node fields are blank. The
     small office distributed with EnergyPlus has no such loop. No other case fails with the
     release, so 45 cases remain.
   - The runtime test loses the small office and runs on the three other buildings. Its bar of at
     least 3 of the 4 buildings is kept, so all three must meet it.
   - The window upgrade is eligible in 36 cases, not 34 as first noted, with 12 excluded. The
     miscount was in the note only. With the small office excluded, 34 eligible cases remain.
4. **Breakdown of the largest changes, recorded after the energy results and before any output
   of the breakdown runs was seen.** The files report no hourly or per-component energy, so the
   three cases with the largest change in an eligible end use are run again with the release and
   two passes (base input), with hourly output requests only: the meters Heating:NaturalGas,
   Heating:Electricity and Fans:Electricity, and Heating Coil Heating Energy and Fan Electricity
   Energy for every coil and fan (`study/locate_changes.py`). The runs must reproduce the annual
   values of the study.
