# Weather

`USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3.epw`: typical meteorological year (TMY3) for Denver
(Aurora-Buckley Air Force Base, WMO 724695), the site of the Denver versions of the U.S. Department
of Energy prototype building models. It is used by the tests in `tests/` (annual small office, room
with an exact solution), by `build/compare_programs.py` and by `study/check_sizing_passes.sh`. The
single room on its design days needs no weather file.

SHA-256: `c7e390b6b3acd4f3e13328115ea81254ac68106bb1503201649eeba4e951f2ee`

It holds the same data as `USA_CO_Denver-Aurora-Buckley.AFB_.724695_TMY3.epw` from the prototype
building models page of energycodes.gov
(https://www.energycodes.gov/sites/default/files/2023-10/USA_CO_Denver-Aurora-Buckley.AFB_.724695_TMY3.epw,
SHA-256 `75841a7b…46ade`, the Denver file of the prototype study). The two differ only in line
endings: this copy ends its lines with LF, the energycodes.gov file with CR LF. Removing the CR
characters from the energycodes.gov file gives this file byte for byte. The prototype study uses
the three energycodes.gov weather files as downloaded, and `study/prepare_inputs.py` checks them
against `results/prototypes/weather.csv`.
