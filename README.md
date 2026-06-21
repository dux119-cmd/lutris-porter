# lutris-porter

Export and import Lutris games via compressed tarballs.

Requires **Python 3.14**

## Install

```sh
pip install -e .
```

(or just run it in place with `python -m lutris_porter`)

## Usage

List installed games:

```sh
lutris-porter --list
```

Export a game (from the `--list` output):

```sh
lutris-porter export GAME OUTPUT-DIR

# exports portable <output-dir>/<game>.tar.zst tarball
```

Import a game (using a previously exported tarball):

```sh
lutris-porter import /path/to/GAME.tar.zst INSTALL-DIR
or
lutris-porter import https://path/to/GAME.tar.zst INSTALL-DIR

# imports game files to <install-dir>/<slug>/...
```

