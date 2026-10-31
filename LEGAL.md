# Legal notice

## What this repository is

tomo_coll_decomp is a reverse-engineering project targeting Tomodachi
Collection (Nintendo DS, game code CCUJ). The goal is to disassemble the
game's ARM9 program and rewrite it as C that the original toolchain turns
back into the same bytes. Any C produced under `src/` will be derived from the
game's own binary by that process. It is not a clean-room reimplementation,
and this project does not claim it is.

## What is licensed, and what is not

- `tools/`, `docs/`, the build scripts and every other file that is original
  work of this project's contributors may be treated as MIT-licensed.
- Any reverse-engineered game source produced under `src/` is distributed
  without any license grant. The contributors claim no ownership of it. The
  game's code, design and assets are the property of Nintendo. Use of that
  source is at your own risk under the law that applies to you.

## What is never distributed

No game data is in this repository or accepted into it: no ROM images, no
extracted archives, no converted assets, no disassembly listings, no vendor
SDK or compiler. Building requires the user's own legally obtained ROM dump;
the tools read it and derive everything locally.

## Trademarks

Nintendo DS and Tomodachi Collection are trademarks of Nintendo. This project
is not affiliated with or endorsed by Nintendo.
