# TODO
 - When exporting, automatically expand any path that start with '~' as the user's home directory prior to further processing.

 - When exporting, exclude the following top-level keys (and any space-indented subsequent child content) from the game's config YML: game_slug, name, script, service, service_id, slug

 - When exporting, exclude the following files/directories relative to the game's directory: config_info, lutris.json, shadercache/, gstreamer-1.0/, dosdevices/{d* through z*}, drive_c/proton_shortcuts/

 - When exporting, allow archives to by chunked into a given MB size (provided via CLI arg), where file chunks are postfixed by a numbered value, like 001, 002, where the padding width is calculated from the size of the gamedir.

 - When importing, handle reading/streaming import archives from a web URL.

 - When importing, if the archive extension is the first chunk (ie: .1, .01, .001, etc) then the reader automatically increments into the next chunk until zstd reports completion of the archive.

 - Alternatively, allow importing from a text-file/URL listing the chunks sequentially, line-by-line, be them files or URLs. In this case, the lines provide the sequence of chunks (no need for automatic increment).

# lutris-porter

Export a Lutris game (files, database row, config, artwork) to a single
compressed tarball, and import it on another machine.

Requires **Python 3.14+**

## Install

```sh
pip install -e .
```

(or just run it in place with `python -m lutris_porter`)

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

By default this compresses at zstd level 12 with a 128 MiB
long-distance-matching window - a good ratio/speed tradeoff for archiving a
game once. Adjust if you want faster exports or a smaller file:

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

- The game's actual install directory is found, in order: an absolute `exe`
  path in config.yml containing the slug, then the database's `directory`
  column, then - for games installed under Lutris's global default games
  folder with a relative `exe` - `system.yml`'s `system.game_path` joined
  with the slug.

- Export streams straight into a zstd-compressed tarball: database.json,
  config.yml, and artwork are written from memory, and the game directory
  is read directly off disk into the compressed stream. Import reverses
  this in a single pass, extracting the game directory's members straight
  to their final destination. Neither direction stages a full copy anywhere
  first - important when a game install is tens of gigabytes. Export writes
  to a `.part` file and only renames it to the final `.tar.zst` on success,
  so a failure never leaves a corrupt archive.

- Any absolute path inside the database row or config YAML that contains
  the slug as a path segment has that segment-and-everything-before-it
  replaced with a placeholder on export, and swapped back for the real
  install path on import. Paths unrelated to the game (e.g. a Wine binary
  path) are left untouched.

- On import, `lastplayed` and `playtime` are cleared and `installed_at` is
  set to the current time, since the import is a fresh install.

- Import refuses to proceed if the slug already exists in the destination
  database, or if the destination install directory already exists, rather
  than silently overwriting anything.

## Tarball layout

Inside the compressed tar, in this order (the importer relies on
`database.json` coming first and `game/` coming last):

```
<slug>/
  database.json     # the games table row, with paths genericized
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
