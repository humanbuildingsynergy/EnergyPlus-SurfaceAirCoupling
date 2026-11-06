"""Prepare the 48 inputs of the prototype study: the 16 DOE commercial prototype buildings for
ASHRAE Standard 90.1-2019 in Miami (1A), Denver (5B) and International Falls (7).

Sources (not redistributed here; download them once, by hand):
  the 16 zips ASHRAE901_<building>_STD2019.zip and the three TMY3 weather files of the prototype
  page https://www.energycodes.gov/prototype-building-models, at
  https://www.energycodes.gov/sites/default/files/2023-10/<file name>
  into <PROTOTYPES>/zip/ and <PROTOTYPES>/weather/ (PROTOTYPES: see configurations.py).
Every zip, every extracted 22.1 input and every weather file must match the SHA-256 in
results/prototypes/sources.csv and weather.csv; the script stops at the first file that is missing
or differs.
Steps: extract the Miami, Denver and International Falls inputs (EnergyPlus 22.1); convert each to
26.2 with the release's transition programs, one version at a time, keeping every warning; write
the study inputs, which are the converted file plus Output:SQLite (<case>_base.idf) and the same
with the window upgrade (<case>_window.idf: every WindowMaterial:SimpleGlazingSystem whose U-factor
and SHGC are both above 1.42 W/(m2 K) and 0.25 is set to these values; written only for the cases
where at least one object qualifies). Nothing else is changed. The run period is checked to be the
full year, and the timestep is left as shipped.
Writes <PROTOTYPES>/v22_1/, v26_2/ and study/, and, in results/prototypes/, sources.csv (checksums,
versions, timestep, window-upgrade eligibility), transition_warnings.csv (every warning line) and
weather.csv (weather file checksums). The checksum of each converted input (transitioned_sha256) is
compared with the published one before sources.csv is written.

Usage (repository root): python3 study/prepare_inputs.py [--cases CASE ...] [--workers N]
With --cases, only those cases are prepared and compared, and no results file is written.
"""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402

ROOT = C.PROTOTYPES
RESULTS = REPO / "results" / "prototypes"
TRANSITION = C.RELEASE / "PreProcess" / "IDFVersionUpdater"
SOURCE_URL = "https://www.energycodes.gov/sites/default/files/2023-10/"
BUILDINGS = ["ApartmentHighRise", "ApartmentMidRise", "Hospital", "HotelLarge", "HotelSmall",
             "OfficeLarge", "OfficeMedium", "OfficeSmall", "OutPatientHealthCare", "RestaurantFastFood",
             "RestaurantSitDown", "RetailStandalone", "RetailStripmall", "SchoolPrimary",
             "SchoolSecondary", "Warehouse"]
CITIES = {"Miami": "1A", "Denver": "5B", "InternationalFalls": "7"}
WEATHER = {"Miami": "USA_FL_Miami.Intl_.AP_.722020_TMY3.epw",
           "Denver": "USA_CO_Denver-Aurora-Buckley.AFB_.724695_TMY3.epw",
           "InternationalFalls": "USA_MN_International.Falls_.Intl_.AP_.727470_TMY3.epw"}
# Transition programs from the file's version (22.1) to the release's (26.2), applied in order.
STEPS = ["22-1-0", "22-2-0", "23-1-0", "23-2-0", "24-1-0", "24-2-0", "25-1-0", "25-2-0", "26-1-0", "26-2-0"]
WINDOW_U, WINDOW_SHGC = 1.42, 0.25  # window upgrade: U-factor [W/(m2 K)] and solar heat gain coefficient
GLAZING = re.compile(r"(WindowMaterial:SimpleGlazingSystem,\s*[^,;]*,[^\n]*\n)"   # class and name
                     r"(\s*)([-\d.Ee+]+)(\s*,\s*!-\s*U-Factor[^\n]*\n)"
                     r"(\s*)([-\d.Ee+]+)(\s*[,;]\s*!-\s*Solar Heat Gain Coefficient)", re.I)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(paths):
    """Stop with the list of source files still to download, if any is missing."""
    missing = [q for q in paths if not q.exists()]
    if missing:
        sys.exit("missing source files; download each into the folder shown (for example with a "
                 "web browser):\n" + "\n".join(f"  {SOURCE_URL + q.name}\n    -> {q.parent}/"
                                               for q in missing))


def check(path, expected):
    got = sha(path)
    if got != expected:
        sys.exit(f"checksum differs: {path}\n  expected {expected}\n  found    {got}\n"
                 f"  the file on energycodes.gov may have been replaced since the study")


def transition(job):
    """Convert one file in its own folder, 22.1 -> 26.2. Returns the case, success and warning lines."""
    case, src = job
    d = ROOT / "work" / case
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    f = d / "in.idf"
    shutil.copy(src, f)
    # The transition programs write Energy+.ini and Transition.audit to the working directory, so
    # each case runs from its own folder of links to the programs and IDDs.
    tools = d / "tools"
    tools.mkdir()
    for x in TRANSITION.iterdir():
        if x.name.startswith("Transition-V") or x.name.endswith("Energy+.idd"):
            (tools / x.name).symlink_to(x)
    warnings, ok = [], True
    log = d / "in.VCpErr"
    for a, b in zip(STEPS[:-1], STEPS[1:]):
        log.unlink(missing_ok=True)  # a step with nothing to report writes no log
        p = subprocess.run([str(tools / f"Transition-V{a}-to-V{b}"), str(f)], cwd=tools,
                           capture_output=True, text=True)
        text = log.read_text(errors="replace") if log.exists() else ""
        if log.exists():
            shutil.copy(log, d / f"V{a}-to-V{b}.VCpErr")
        ver = re.search(r"^\s*Version,\s*([^;]+);", f.read_text(errors="replace"), re.M | re.I)
        want = ".".join(b.split("-")[:2])
        if p.returncode != 0 or not ver or ver.group(1).strip() != want or "** Severe" in text:
            ok = False
        for line in text.splitlines():
            if "** Warning **" in line or "** Severe" in line or "~~~" in line:
                warnings.append({"case": case, "step": f"{a}->{b}", "line": line.strip()})
        if not ok:
            warnings.append({"case": case, "step": f"{a}->{b}", "line": f"FAILED rc={p.returncode} "
                             f"version={ver.group(1) if ver else None} {p.stdout[-300:]}"})
            break
    return case, ok, warnings


def window_upgrade(text):
    """Set every simple glazing system to U 1.42 and SHGC 0.25 where both are lower than shipped.
    Returns the new text, the number of glazing objects and the number upgraded."""
    n_all, n_up = 0, 0

    def sub(m):
        nonlocal n_all, n_up
        n_all += 1
        u, shgc = float(m.group(3)), float(m.group(6))
        if WINDOW_U < u and WINDOW_SHGC < shgc:
            n_up += 1
            return f"{m.group(1)}{m.group(2)}{WINDOW_U}{m.group(4)}{m.group(5)}{WINDOW_SHGC}{m.group(7)}"
        return m.group(0)

    new = GLAZING.sub(sub, text)
    n_class = len(re.findall(r"^\s*WindowMaterial:SimpleGlazingSystem,", text, re.I | re.M))
    if n_class != n_all:
        sys.exit(f"glazing parse mismatch: {n_class} objects, {n_all} parsed")
    return new, n_all, n_up


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", nargs="*", help="prepare only these cases (e.g. RetailStandalone_Denver)")
    ap.add_argument("--workers", type=int, default=os.cpu_count(), help="parallel conversions")
    a = ap.parse_args()
    published = pd.read_csv(RESULTS / "sources.csv").set_index("case")
    weather_sha = pd.read_csv(RESULTS / "weather.csv").set_index("file").sha256
    cases = [f"{b}_{c}" for b in BUILDINGS for c in CITIES]
    if a.cases:
        unknown = set(a.cases) - set(cases)
        if unknown:
            sys.exit(f"unknown cases: {sorted(unknown)}")
        cases = [c for c in cases if c in a.cases]
    full = len(cases) == len(BUILDINGS) * len(CITIES)

    # Sources: present and identical to those of the study.
    weather = [ROOT / "weather" / WEATHER[city] for city in sorted({published.loc[c, "city"] for c in cases})]
    zips = [ROOT / "zip" / z for z in sorted({published.loc[c, "zip"] for c in cases})]
    require(weather + zips)
    for w in weather:
        check(w, weather_sha[w.name])
    for z in zips:
        check(z, published[published.zip == z.name].zip_sha256.iloc[0])

    for d in ("v22_1", "v26_2", "study", "work"):
        if full:
            shutil.rmtree(ROOT / d, ignore_errors=True)  # no stale inputs from an earlier run
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    rows = []
    for b in BUILDINGS:
        z = ROOT / "zip" / f"ASHRAE901_{b}_STD2019.zip"
        for city in CITIES:
            case = f"{b}_{city}"
            if case not in cases:
                continue
            name = f"ASHRAE901_{b}_STD2019_{city}.idf"
            with zipfile.ZipFile(z) as zf:
                (ROOT / "v22_1" / name).write_bytes(zf.read(name))
            check(ROOT / "v22_1" / name, published.loc[case, "source_sha256"])
            rows.append({"building": b, "city": city, "climate_zone": CITIES[city],
                         "case": case, "zip": z.name, "zip_sha256": sha(z),
                         "source_idf": name, "source_sha256": sha(ROOT / "v22_1" / name)})
    src = pd.DataFrame(rows)

    with ProcessPoolExecutor(min(a.workers, len(src))) as ex:
        res = list(ex.map(transition, [(r.case, ROOT / "v22_1" / r.source_idf) for r in src.itertuples()]))
    warn, status = [], {}
    for case, ok, w in res:
        status[case] = ok
        warn += w
    if not all(status.values()):
        sys.exit(f"transition failed: {[c for c, ok in status.items() if not ok]}")

    extra = []
    for r in src.itertuples():
        t = (ROOT / "work" / r.case / "in.idf").read_text(errors="replace")
        ver = re.search(r"^\s*Version,\s*([^;]+);", t, re.M | re.I).group(1).strip()
        if ver != "26.2":
            sys.exit(f"{r.case}: version {ver}")
        (ROOT / "v26_2" / f"{r.case}.idf").write_text(t)
        rp = re.findall(r"^\s*RunPeriod,\s*\n([^;]*);", t, re.M | re.I)
        fields = [re.sub(r"!.*", "", x).strip().rstrip(",") for x in rp[0].splitlines()] if len(rp) == 1 else []
        # RunPeriod fields 2-3 and 5-6: begin month and day, end month and day
        full_year = len(rp) == 1 and fields[1:3] == ["1", "1"] and fields[4:6] == ["12", "31"]
        if not full_year:
            sys.exit(f"{r.case}: run period is not one full year: {rp}")
        ts = re.findall(r"^\s*Timestep,\s*(\d+)\s*;", t, re.M | re.I)
        if re.search(r"^\s*Output:SQLite\s*,", t, re.M | re.I):
            sys.exit(f"{r.case}: already has Output:SQLite")
        base = t + "\n  Output:SQLite,SimpleAndTabular;\n"
        (ROOT / "study" / f"{r.case}_base.idf").write_text(base)
        win, n_all, n_up = window_upgrade(base)
        eligible = n_up > 0
        if eligible:
            (ROOT / "study" / f"{r.case}_window.idf").write_text(win)
        extra.append({"case": r.case, "version_after": ver, "timestep": ts[0] if len(ts) == 1 else ts,
                      "transitioned_sha256": sha(ROOT / "v26_2" / f"{r.case}.idf"),
                      "n_transition_warnings": sum(1 for w in warn if w["case"] == r.case
                                                   and "** Warning **" in w["line"]),
                      "n_simple_glazing": n_all, "n_glazing_upgraded": n_up,
                      "window_savings_eligible": eligible, "weather": WEATHER[r.city]})
    src = src.merge(pd.DataFrame(extra), on="case")

    same = src.set_index("case").transitioned_sha256 == published.loc[src.case, "transitioned_sha256"]
    print(f"converted inputs identical to those of the study: {int(same.sum())} of {len(same)}")
    if not same.all():
        print("  differ:", sorted(same.index[~same]))
    print(src[["case", "timestep", "n_transition_warnings", "n_simple_glazing", "n_glazing_upgraded",
               "window_savings_eligible"]].to_string(index=False))
    if not full:
        return
    src.to_csv(RESULTS / "sources.csv", index=False)
    pd.DataFrame(warn).to_csv(RESULTS / "transition_warnings.csv", index=False)
    pd.DataFrame([{"city": c, "file": f, "sha256": sha(ROOT / "weather" / f)} for c, f in WEATHER.items()]
                 ).to_csv(RESULTS / "weather.csv", index=False)
    w = pd.DataFrame(warn)
    w = w[w.line.str.contains(r"\*\* Warning|\*\* Severe")]
    print("\nwarning kinds:", w.line.str.replace(r"name=.*", "name=...", regex=True)
          .str.replace(r"\d+", "#", regex=True).value_counts().head(15).to_string())


if __name__ == "__main__":
    main()
