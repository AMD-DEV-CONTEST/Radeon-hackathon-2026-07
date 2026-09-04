# PHREEQC Example 2 qualification fixtures

These byte-exact fixtures originate from the official PHREEQC 3.9.0-17591 release asset
`phreeqc-3.9.0-17591.tar.gz`, downloaded from the `phreeqc-dev/phreeqc3` v3.9.0
GitHub release linked by the USGS repository. The archive SHA-256 is
`fda26290d96f6785e440c05217bf4b9fa9cd1efbf2fee155591e05b30165c6cd`.

`example2.pqi` is an unchanged copy of upstream `examples/ex2` (SHA-256
`bff24cafb046ebcb0fd54263f6617fd3bddea1fe21da079d9e13af5ebecdbcc5`).
It is titled “Temperature dependence of solubility of gypsum and anhydrite” and
already contains the upstream `SELECTED_OUTPUT` block; no scientific or output
instructions were added or changed.

`example2-selected-output.txt` was freshly produced from that input in a clean
`C` locale with the release-built executable and the release `phreeqc.dat`.
Two independent clean-directory executions exited zero and produced identical
files. Its SHA-256 is
`d83b5148c6350aaac58c18ba5cffa4b8837b0254f7d8cac4a8d45c7681d6cfec`.
It has 53 lines: one exact header and 52 data rows (one `i_soln`, 51 `react`).

Build provenance for this qualification instance:

- self-reported banner: `PHREEQC 3.8.9, October 13, 2025`;
- database SHA-256: `5b80d45c989cd1db7aab485e198321ba550d5902be8097c8be26d85ba03da278`;
- executable SHA-256: `68f3fbab44c681989cb967240de2c3629177553099cbbe8703440a188cd796c5`;
- compiler: `c++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`;
- build tool: `GNU Make 4.3`.

The executable digest is evidence for this build only; it is not expected to be
portable across compilers, flags, operating systems, or other toolchains. No
PHREEQC executable or database is versioned here.
