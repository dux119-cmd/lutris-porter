# lutris-porter

Export a Lutris game (files, database row, config, artwork) to a single
zstd-compressed tarball, and import it on another machine.

Requires **Python 3.14+**

## Install

```sh
pip install -e .
```

(or just run it in place with `python -m lutris_porter`, requires PyYAML)

## Usage

List installed game slugs:

```sh
lutris-porter -l
```

Export a game:

```sh
lutris-porter export <slug> <output-dir>
# writes <output-dir>/<slug>.tar.zst
```

By default this compresses at zstd level 12 with a 128 MiB long-distance-matching
window - a good ratio/speed tradeoff for archiving a game once. Adjust if you
want faster exports or a smaller file:

```sh
lutris-porter export <slug> <output-dir> --zstd-level 22 --zstd-window-log 31
```

- `--zstd-level`: compression level (valid range: 1 to 22; higher is
  smaller but slower)
- `--zstd-window-log`: back-reference window size as a power of two, e.g.
  `27` = 128 MiB (valid range: 10 to 31, or 0 for automatic)

Import a game on another machine:

```sh
lutris-porter import <slug>.tar.zst <install-dir>
# installs game files to <install-dir>/<slug>, registers it in pga.db,
# writes its config.yml, and copies any banner/coverart/logo
```

Import always works regardless of which level/window-log the export used -
the decompressor is opened with its maximum window size, so it never needs
matching flags.

## How it works

- The game's actual install directory is found, in order: an absolute
  `exe` path in config.yml containing the slug, then the database's
  `directory` column, then - for games installed under Lutris's global
  default games folder with a relative `exe` - `system.yml`'s
  `system.game_path` joined with the slug.
- Export streams straight into a zstd-compressed tarball: database.yml,
  config.yml, and artwork are written from memory, and the game
  directory is read directly off disk into the compressed stream. Import
  reverses this in a single pass, extracting the game directory's
  members straight to their final destination. Neither direction stages
  a full copy anywhere first - important when a game install is tens of
  gigabytes. Export writes to a `.part` file and only renames it to the
  final `.tar.zst` on success, so a failure never leaves a corrupt archive.
- Any absolute path inside the database row or config YAML that
  contains the slug as a path segment has that segment-and-everything-before-it
  replaced with a placeholder on export, and swapped back for the real
  install path on import. Paths unrelated to the game (e.g. a Wine
  binary path) are left untouched.
- On import, `lastplayed` and `playtime` are cleared and `installed_at`
  is set to the current time, since the import is a fresh install.
- Import refuses to proceed if the slug already exists in the
  destination database, or if the destination install directory already
  exists, rather than silently overwriting anything.

## Tarball layout

Inside the zstd-compressed tar, in this order (the importer relies on
database.yml coming first and game/ coming last):

```
<slug>/
  database.yml      # the games table row, with paths genericized
  config.yml         # the Lutris game config, with paths genericized
  banner.png|jpg     # if present
  coverart.png|jpg   # if present
  logo.png|jpg        # if present
  game/              # the game's install directory contents
```

## Tests

```sh
pip install pytest
pytest
```
