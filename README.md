# lutris-porter

Export and import Lutris games using compressed standalone archives.

Requires **Python 3.14**

## Usage

List installed games:

```sh
./lutris-porter.py --list
```

Export a game (from the `--list` output):

```sh
./lutris-porter.py export GAME ARCHIVES-DIR

# exports portable <archives-dir>/<game>.tar.zst archive
```

Import a game from a previously exported archive:

```sh
./lutris-porter.py import /path/to/GAME.tar.zst GAMES-PARENT-DIR
./lutris-porter.py import https://path/to/GAME.tar.zst GAMES-PARENT-DIR

# imports the game into <games-parent-dir>/<game>
```


