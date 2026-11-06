"""Program configurations shared by the scripts in tests/ and study/.

Two EnergyPlus installs are used: the 26.2.0 release as distributed, and the same release built
from source with the patches in patches/ (build/build_patched.sh). The patched program behaves
exactly like the release until one of the environment variables below is set:

  SURFACE_AIR_PASSES   maximum extra passes per zone timestep (default 0: off)
  SURFACE_AIR_TOL      stop when no zone air temperature changes by more than this [C] between
                       passes (default 1e-9)
  SURFACE_AIR_OUTSIDE  1 = each pass also solves the outside surface heat balance again
  SURFACE_AIR_HVAC     1 = each pass also repeats the load prediction and the HVAC simulation
  SURFACE_AIR_LOG      1 = report each zone timestep that ends at the pass limit
  INSIDE_SURFACE_TOL   inside surface convergence tolerance [C] (EnergyPlus default 0.002)

The install folders default to ~/EnergyPlus/EnergyPlus-26-2-0 and
~/EnergyPlus/EnergyPlus-26-2-0-surface-air, where build/install_release.sh and
build/build_patched.sh put them. Set ENERGYPLUS_RELEASE or ENERGYPLUS_PATCHED to use others.
"""

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent
RELEASE = Path(os.environ.get("ENERGYPLUS_RELEASE", Path.home() / "EnergyPlus" / "EnergyPlus-26-2-0"))
PATCHED = Path(os.environ.get("ENERGYPLUS_PATCHED",
                              Path.home() / "EnergyPlus" / "EnergyPlus-26-2-0-surface-air"))
# Folder of the 90.1-2019 prototype inputs: downloads in zip/ and weather/, prepared inputs in
# study/ (study/prepare_inputs.py). Set ENERGYPLUS_PROTOTYPES to use another.
PROTOTYPES = Path(os.environ.get("ENERGYPLUS_PROTOTYPES", Path.home() / "EnergyPlus" / "prototypes" / "STD2019"))

# The four configurations of the paper (its Table 1). Each maps to (install, environment).
# "two_passes" is the correction examined for practical use; "converged" is the reference.
COUPLED = {"SURFACE_AIR_OUTSIDE": "1", "SURFACE_AIR_HVAC": "1"}
CONFIGURATIONS = {
    "release": (RELEASE, {}),
    "one_pass": (PATCHED, COUPLED | {"SURFACE_AIR_PASSES": "1"}),
    "two_passes": (PATCHED, COUPLED | {"SURFACE_AIR_PASSES": "2"}),
    "converged": (PATCHED, COUPLED | {"SURFACE_AIR_PASSES": "50", "SURFACE_AIR_TOL": "1e-9",
                                      "INSIDE_SURFACE_TOL": "1e-8"}),
}

# Further configurations used only by the tests on simple models, to separate the parts of the
# correction. All solve to agreement (up to 50 passes, 1e-9 C) with the tighter inside surface
# tolerance; they differ in which balances are solved again in each pass.
TIGHT = {"SURFACE_AIR_PASSES": "50", "SURFACE_AIR_TOL": "1e-9", "INSIDE_SURFACE_TOL": "1e-8"}
TEST_CONFIGURATIONS = {
    "passes_off": (PATCHED, {}),  # must reproduce the release exactly
    "inside_faces": (PATCHED, TIGHT),
    "both_faces": (PATCHED, TIGHT | {"SURFACE_AIR_OUTSIDE": "1"}),
}

# Every variable the patches read, so that reused worker processes can be reset.
VARIABLES = ("SURFACE_AIR_PASSES", "SURFACE_AIR_TOL", "SURFACE_AIR_OUTSIDE", "SURFACE_AIR_HVAC",
             "SURFACE_AIR_LOG", "INSIDE_SURFACE_TOL")

# Lines the patched program writes to eplusout.err.
# Per environment, after the run: timesteps, mean extra passes, largest number of passes, and the
# number of timesteps that ended at the pass limit.
PASS_STATISTICS = re.compile(r"Surface-air passes: (.+?): (\d+) timesteps, mean extra passes ([\d.]+), "
                             r"max (\d+), not converged (\d+)")
# With SURFACE_AIR_LOG=1, one line per zone timestep that ended at the pass limit.
PASS_LIMIT_LINE = re.compile(r"Surface-air passes not converged: (.+?) (\d\d)/(\d\d) hour (\d+) ts (\d+), "
                             r"zone (.+?), last change (\S+) C, ZT last passes((?: \S+)+)")


def program(name):
    """Install folder and environment of a named configuration (paper or test)."""
    return (CONFIGURATIONS | TEST_CONFIGURATIONS)[name]


def run_environment(extra):
    """A copy of os.environ with every patch variable removed, then `extra` added."""
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    env.update(extra)
    return env
