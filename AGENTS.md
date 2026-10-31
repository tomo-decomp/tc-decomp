# Agent Guidelines for `tomo_coll_decomp`

`tomo_coll_decomp` is a work-in-progress decompilation of Tomodachi Collection
(Nintendo DS, `CCUJ`). It is one of the decompilation projects under
`dsdecomp/`, alongside `pokeplatinum` and `pokeheartgold`, and follows the same
shape: matching C under `src/`, tooling under `tools/`, notes under `docs/`.

## Ground rules for this project

- **Everything in `src/` must match.** A file is only finished when
  `python3 tools/match.py file <path>` reports `match` — byte-identical to the
  original function, including its literal pool. Do not "clean up" a matching
  file unless you have re-run the check afterwards.
- **No game data, ever.** No ROM images, no extracted archives, no converted
  assets, no SDK or compiler binaries in git. `extract/`, `build/` and
  `subprojects/*/` are derived from the user's own dump or from pinned public
  wraps, and stay out of the repository.
- **Tooling and docs are original work** (MIT, see `LICENSE`). `src/` is
  reverse-engineered from the game and carries no license grant (`LEGAL.md`).
- **Follow the project's conventions** in `docs/decompilation.md`: one function
  per file named after its address, `UnkNNNNNNNN`/`unk_NNN`/`pad_NNN` naming,
  address-encoded symbol names for calls and data.
- **Do not change the compiler flags** in `tools/match.py` or `meson.build` to
  make a file match. If a function will not match, the source is wrong, or the
  file needs a narrower flag scope that must be justified in the commit.
- **Do not add files to `src/` that do not match.** Partial or approximate
  reconstructions belong in notes, not in `src/`.

## Publishing

Do not post to GitHub (issues, pull requests, discussions, comments) on this
project's behalf, and do not write release notes or review replies with an
agent. Human-to-human review is the bottleneck; generated text wastes it.
