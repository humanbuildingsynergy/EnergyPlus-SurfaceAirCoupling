#!/usr/bin/env bash
# Check, before the prototype study, that the passes run on the sizing design days, so that the
# autosized capacities of the patched configurations come from sizing with the passes on.
# Runs the small office distributed with EnergyPlus (Denver) with sizing only (weather-file run
# period switched off) with three configurations of configurations.py:
#   release     the release
#   passes_off  the patched program with the passes off (must size exactly like the release)
#   two_passes  the primary corrected configuration
# and records each run's last eplusout.err line, the pass statistics per environment that the
# patched program writes, and how many "Sizing Information" lines of eplusout.eio differ from the
# release's. Only the counts are recorded, not the sizes.
# Reads <runs>/release_check/release/office_ts04/in.idf, written by build/compare_programs.py (run
# it first), and weather/USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3.epw. Raw runs:
# <runs>/sizing_passes_check/. Writes results/prototypes/sizing_passes_check.txt.
# Usage (repository root): study/check_sizing_passes.sh [--runs DIR]     (default runs/)
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
RUNS="$REPO/runs"
if [ "${1:-}" = "--runs" ]; then RUNS=$(cd "$2" && pwd); fi
SRC="$RUNS/release_check/release/office_ts04/in.idf"
W="$REPO/weather/USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3.epw"
D="$RUNS/sizing_passes_check"
OUT="$REPO/results/prototypes/sizing_passes_check.txt"
[ -f "$SRC" ] || { echo "missing $SRC; run build/compare_programs.py first" >&2; exit 1; }

# Install folder and environment of a named configuration, from configurations.py: prints the
# install folder, then "-u VAR" for every patch variable (so none leaks in from the shell), then
# the VAR=value settings of the configuration, ready for env(1).
config() {
  PYTHONPATH="$REPO" python3 -c '
import sys, configurations as C
install, env = C.program(sys.argv[1])
print(install, *[f"-u {v}" for v in C.VARIABLES], *[f"{k}={v}" for k, v in env.items()])' "$1"
}
PATCHED=$(PYTHONPATH="$REPO" python3 -c 'import configurations as C; print(C.PATCHED)')

rm -rf "$D"
mkdir -p "$D"/release "$D"/passes_off "$D"/two_passes "$(dirname "$OUT")"
# Switch off the weather-file run period (SimulationControl), so only sizing periods run.
sed -E 's/^( *)YES,( *!- Run Simulation for Weather File Run Periods)/\1No,\2/' "$SRC" > "$D/in.idf"
grep -q "No, *!- Run Simulation for Weather File Run Periods" "$D/in.idf"

for c in release passes_off two_passes; do
  read -r install settings <<< "$(config "$c")"
  # shellcheck disable=SC2086  # settings are separate env(1) arguments
  (cd "$D/$c" && env $settings "$install/energyplus" -w "$W" -d . ../in.idf >/dev/null) &
done
wait

sizing() { grep "Sizing Information" "$1/eplusout.eio"; }
ndiff() { diff <(sizing "$D/release") <(sizing "$1") | grep -c '^<' || true; }
{
  echo "Sizing-only run of the small office distributed with EnergyPlus, Denver: do the passes run on the sizing design days?"
  echo "date: $(date '+%F %H:%M %Z')"
  echo "patched program: $("$PATCHED/energyplus" --version)"
  echo "run: weather-file run period off, so every non-warmup environment below is a sizing design day"
  for c in release passes_off two_passes; do
    echo "== $c: $(tail -1 "$D/$c/eplusout.err" | sed 's/^ *\** *//')"
    grep -o "Surface-air passes.*" "$D/$c/eplusout.err" || echo "(no surface-air pass lines)"
  done
  echo "sizing lines in .eio: $(sizing "$D/release" | wc -l | tr -d " ")"
  echo "differing from release: passes_off $(ndiff "$D/passes_off"), two_passes $(ndiff "$D/two_passes")"
} | tee "$OUT"
