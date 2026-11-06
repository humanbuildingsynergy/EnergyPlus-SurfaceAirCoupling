#!/usr/bin/env bash
# Runtime of the patched program with and without its passes: one annual run of the small office
# per configuration, all started at once (each run uses one core; keep the machine otherwise
# idle). Configurations: release, passes_off (patched program, no variable set), inside_faces,
# both_faces and converged, as defined in configurations.py. The input is the release's office
# input written by build/compare_programs.py (<runs>/release_check/release/office_ts04/in.idf).
# Writes results/passes/runtime.csv: return code, wall time [s] and, for the patched program, the
# annual timesteps, mean extra passes, largest number of passes and timesteps that ended at the
# limit, from the line the program writes to eplusout.err. Raw runs: <runs>/pass_runtime/.
# Needs GNU date (%N). ENERGYPLUS_RELEASE and ENERGYPLUS_PATCHED override the install folders,
# RESULTS the output folder.
# Usage (repository root): tests/pass_runtime.sh [runs] [configuration ...]
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNS=$(realpath "${1:-runs}")
shift $(( $# > 0 ? 1 : 0 ))
CONFIGS=("$@")
[ ${#CONFIGS[@]} -gt 0 ] || CONFIGS=(release passes_off inside_faces both_faces converged)
REL=${ENERGYPLUS_RELEASE:-"$HOME/EnergyPlus/EnergyPlus-26-2-0"}
PAT=${ENERGYPLUS_PATCHED:-"$HOME/EnergyPlus/EnergyPlus-26-2-0-surface-air"}
EPW="$ROOT/weather/USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3.epw"
IDF="$RUNS/release_check/release/office_ts04/in.idf"
W="$RUNS/pass_runtime"
OUT=${RESULTS:-"$ROOT/results/passes"}/runtime.csv
[ -f "$IDF" ] || { echo "missing $IDF; run build/compare_programs.py first" >&2; exit 1; }
rm -rf "$W"
mkdir -p "$W" "$(dirname "$OUT")"

# The same settings as configurations.py. Every patch variable is unset first, so that nothing
# from the calling shell leaks into a run.
CLEAR=(-u SURFACE_AIR_PASSES -u SURFACE_AIR_TOL -u SURFACE_AIR_OUTSIDE -u SURFACE_AIR_HVAC
       -u SURFACE_AIR_LOG -u INSIDE_SURFACE_TOL)
TIGHT=(SURFACE_AIR_PASSES=50 SURFACE_AIR_TOL=1e-9 INSIDE_SURFACE_TOL=1e-8)

run() {  # configuration install [VAR=value ...]
  local n=$1 e=$2
  shift 2
  mkdir -p "$W/$n"
  (
    cd "$W/$n"
    s=$(date +%s.%N)
    env "${CLEAR[@]}" "$@" "$e/energyplus" -w "$EPW" -d . "$IDF" > run.log 2>&1
    rc=$?
    t=$(date +%s.%N)
    printf '%s,%s,%.1f\n' "$n" "$rc" "$(echo "$t - $s" | bc)" > timing.csv
  ) &
}

for n in "${CONFIGS[@]}"; do
  case $n in
    release)      run release "$REL" ;;
    passes_off)   run passes_off "$PAT" ;;
    inside_faces) run inside_faces "$PAT" "${TIGHT[@]}" ;;
    both_faces)   run both_faces "$PAT" "${TIGHT[@]}" SURFACE_AIR_OUTSIDE=1 ;;
    converged)    run converged "$PAT" "${TIGHT[@]}" SURFACE_AIR_OUTSIDE=1 SURFACE_AIR_HVAC=1 ;;
    *) echo "unknown configuration: $n" >&2; exit 1 ;;
  esac
done
wait

{
  echo "configuration,returncode,wall_s,annual_timesteps,mean_extra_passes,max_passes,not_converged"
  for n in "${CONFIGS[@]}"; do
    # The office input names its run period ANNUAL.
    stat=$( (grep -h "Surface-air passes: ANNUAL" "$W/$n/eplusout.err" 2>/dev/null || true) | tail -1 |
      sed -E 's/.*: ([0-9]+) timesteps, mean extra passes ([0-9.]+), max ([0-9]+), not converged ([0-9]+).*/\1,\2,\3,\4/')
    echo "$(cat "$W/$n/timing.csv"),${stat:-,,,}"
  done
} > "$OUT"
cat "$OUT"
