"""Check that another program, or a configuration of the patched program, computes exactly what
the release computes.

Both run the same inputs, taken from the release's ExampleFiles: the single room on its two design
days (floating, and with the ideal air system of tests/single_room.py), with the three zone air
schemes at 4 and 60 timesteps per hour, and the annual small office prototype (Denver) at 4 per
hour. Room temperatures and ideal loads are compared value by value, the office by its annual
results. Writes results/release_check/release_vs_<name>.csv; a row with n_different 0 is identical.
The release run of the office input, <runs>/release_check/release/office_ts04/in.idf, is also the
input of tests/pass_limits.py, tests/pass_runtime.sh and study/check_sizing_passes.sh.
Usage (repository root):
  python3 build/compare_programs.py --test passes_off           # patched program, passes off
  python3 build/compare_programs.py --test-install DIR --name source_build   # any other install
  [--runs runs] [--results results/release_check] [--workers 8]
"""

import argparse
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import configurations as C  # noqa: E402
import single_room as room  # noqa: E402
import _common as common  # noqa: E402

OFFICE = "ASHRAE901_OfficeSmall_STD2019_Denver.idf"


def jobs_for(install, extra, source, runs, label):
    """Room and office jobs for one program; inputs always come from the release (`source`)."""
    box = (Path(source) / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text()
    office = (Path(source) / "ExampleFiles" / OFFICE).read_text()
    room_jobs = [(str(install), room.make_idf(box, case, ts, algo), f"{label}/room_{case}_{algo}_ts{ts:02d}",
                  str(runs), case == "ideal", extra)
                 for case in ("free", "ideal") for algo in room.ALGOS for ts in (4, 60)]
    office_job = (str(install), str(common.WEATHER), common.office_idf(office, 4), f"{label}/office_ts04",
                  str(runs), extra)
    return room_jobs, office_job


def run_office(args):
    """Annual run with the weather file; returns the run name and the return code."""
    eplus, epw, idf_text, name, runs, extra = args
    d = (Path(runs) / name).resolve()  # EnergyPlus runs inside d, so -d must be absolute
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(idf_text)
    t0 = time.time()
    proc = subprocess.run([str(Path(eplus) / "energyplus"), "-w", epw, "-d", str(d), "in.idf"],
                          cwd=d, env=C.run_environment(extra), capture_output=True, text=True)
    err = (d / "eplusout.err").read_text(errors="replace") if (d / "eplusout.err").exists() else ""
    return {"case": name, "returncode": proc.returncode, "wall_s": round(time.time() - t0, 1),
            "n_severe": len(re.findall(r"\*\* Severe  \*\*", err))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--test", choices=list(C.CONFIGURATIONS | C.TEST_CONFIGURATIONS),
                       help="a configuration from configurations.py (passes_off for the patched "
                            "program with every variable unset; release repeats the release)")
    which.add_argument("--test-install", help="install folder of another program, e.g. an "
                                              "unmodified build of the v26.2.0 source")
    ap.add_argument("--name", help="label of --test-install in the output file name")
    ap.add_argument("--runs", default=str(REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(REPO / "results" / "release_check"),
                    help="folder for the comparison table")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    if a.test_install:
        if not a.name:
            ap.error("--test-install needs --name")
        test, extra, name = Path(a.test_install).expanduser(), {}, a.name
    else:
        (test, extra), name = C.program(a.test), a.test
    ref = C.RELEASE
    runs = Path(a.runs).resolve() / "release_check"
    # Folder names under <runs>/release_check/; a repeat of the release gets its own.
    label = name if name != "release" else "release_repeat"

    box_r, office_r = jobs_for(ref, {}, ref, runs, "release")
    box_t, office_t = jobs_for(test, extra, ref, runs, label)
    with ProcessPoolExecutor(a.workers) as ex:
        logs = list(ex.map(room.run, box_r + box_t))
        logs += list(ex.map(run_office, [office_r, office_t]))
    bad = [lg for lg in logs if lg.get("returncode") != 0]
    if bad:
        print("Failed runs:", bad)
        sys.exit(1)

    rows = []
    for jr, jt in zip(box_r, box_t):
        case = jr[2].split("/", 1)[1]
        vr = room.hour_end_series(runs / jr[2] / "eplusout.sql")
        vt = room.hour_end_series(runs / jt[2] / "eplusout.sql")
        # Every reported value after warmup: temperatures [C] and, for the ideal case, loads [J].
        keys = ["env", "var", "key", "hour", "minute"]
        m = vr.merge(vt, on=keys, suffixes=("_ref", "_test"))
        diff = (m.value_ref - m.value_test).abs()
        rows.append({"case": case, "n_values": len(m), "max_abs_diff": diff.max(),
                     "n_different": int((diff > 0).sum())})
    mr = common.annual_metrics(runs / office_r[3] / "eplusout.sql")
    mt = common.annual_metrics(runs / office_t[3] / "eplusout.sql")
    for k in mr:
        if pd.notna(mr[k]) and mr[k] != 0:
            rows.append({"case": f"office_ts04:{k}", "n_values": 1,
                         "max_abs_diff": abs(mr[k] - mt[k]), "n_different": int(mr[k] != mt[k]),
                         "rel_diff": abs(mt[k] / mr[k] - 1)})
    df = pd.DataFrame(rows)
    out = Path(a.results) / f"release_vs_{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    n = int(df.n_different.sum())
    print(f"\n{'IDENTICAL' if n == 0 else f'{n} values differ'} "
          f"(max abs diff {df.max_abs_diff.max():.3g}). Written to {out}")


if __name__ == "__main__":
    main()
