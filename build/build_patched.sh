#!/usr/bin/env bash
# Build the patched program: clone EnergyPlus at release tag v26.2.0, check that the tag is the
# commit the release was built from (4bd7a1f26f), apply the patches in patches/ and compile.
# The result is installed with the layout of a release in ~/EnergyPlus/EnergyPlus-26-2-0-surface-air
# (the default of ENERGYPLUS_PATCHED in configurations.py). With no SURFACE_AIR_* variable set,
# it computes exactly what the release computes (build/compare_programs.py checks this).
#
# Needs git, cmake >= 3.20 and a C++ compiler (the paper's build used GCC 13.3 on Ubuntu 24.04).
# gfortran is optional: without it, ExpandObjects is linked from the release install, which only
# HVACTemplate inputs need. Build files go to ~/EnergyPlus/src and ~/EnergyPlus/build.
# Usage (repository root): build/build_patched.sh [install folder]     JOBS=N sets parallel jobs.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
URL=https://github.com/NatLabRockies/EnergyPlus.git
TAG=v26.2.0
COMMIT=4bd7a1f26fb749a83257855aba6760e26c8a3c8f
ROOT="$HOME/EnergyPlus"
PREFIX=${1:-"$ROOT/EnergyPlus-26-2-0-surface-air"}
NAME=$(basename "$PREFIX")
SRC="$ROOT/src/$NAME"
BUILD="$ROOT/build/$NAME"
RELEASE=${ENERGYPLUS_RELEASE:-"$ROOT/EnergyPlus-26-2-0"}
JOBS=${JOBS:-$(nproc)}

for tool in git cmake c++; do
  command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }
done
FORTRAN=OFF
command -v gfortran >/dev/null && FORTRAN=ON

if [ -e "$SRC" ]; then
  echo "$SRC exists; remove it to rebuild from a clean clone" >&2
  exit 1
fi
git clone --depth 1 --branch "$TAG" "$URL" "$SRC"
[ "$(git -C "$SRC" rev-parse HEAD)" = "$COMMIT" ] || { echo "tag $TAG is not commit $COMMIT" >&2; exit 1; }
git -C "$SRC" apply --verbose "$HERE"/patches/*.patch

cmake -S "$SRC" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_FORTRAN="$FORTRAN" \
  -DBUILD_TESTING=OFF \
  -DLINK_WITH_PYTHON=OFF \
  -DCMAKE_INSTALL_PREFIX="$PREFIX"
cmake --build "$BUILD" -j "$JOBS"
cmake --install "$BUILD"

# Complete the install where the install step does not match the release layout: the data
# dictionary, the example files that the tests read, and ExpandObjects without gfortran.
[ -f "$PREFIX/Energy+.idd" ] || cp "$BUILD/Products/Energy+.idd" "$PREFIX/"
[ -d "$PREFIX/ExampleFiles" ] || ln -s "$SRC/testfiles" "$PREFIX/ExampleFiles"
if [ ! -x "$PREFIX/ExpandObjects" ] && [ -x "$RELEASE/ExpandObjects" ]; then
  ln -s "$RELEASE/ExpandObjects" "$PREFIX/ExpandObjects"
  echo "ExpandObjects not built (no gfortran); linked the release's copy."
fi

"$PREFIX/energyplus" --version
echo "Installed to $PREFIX"
