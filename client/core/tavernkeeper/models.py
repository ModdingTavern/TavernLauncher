"""What TavernKeeper knows, kept apart from the widgets that show it.

One Models per window, made before any tab, so a tab that fails to build takes
nothing with it and one tab can read what another found.
"""
from collections import namedtuple

Player = namedtuple("Player", "id name")


class Roster:
    """Who is online, from player list-detailed."""

    def __init__(self):
        self.players = []
        self.positions = {}
        self.chunks = {}

    def update(self, rows):
        players, positions, chunks = [], {}, {}
        for row in rows:
            name = row.get("Username") or row.get("username") if isinstance(row, dict) else None
            if name and str(name) not in positions:
                players.append(Player(row.get("Id", row.get("id")), str(name)))
                positions[str(name)] = row.get("Position")
                chunks[str(name)] = row.get("Chunk")
        self.players = players
        self.positions = positions
        self.chunks = chunks

    def find(self, name):
        for player in self.players:
            if player.name == name:
                return player
        return None


class Selection:
    """What Find & Select has found and picked. Entries are (entity id, name)."""

    def __init__(self):
        self.nearby = []
        self.checked = set()
        self.groups = {}
        self.group = None
        self.history = []
        self.current = None

    def forget(self, ids):
        """Drops destroyed objects from everything that lists them."""
        gone = set(ids)
        self.nearby = [e for e in self.nearby if e[0] not in gone]
        self.checked -= gone
        self.history = [e for e in self.history if e[0] not in gone]
        for name in list(self.groups):
            self.groups[name] = [e for e in self.groups[name] if e[0] not in gone]
        if self.current and self.current[0] in gone:
            self.current = None

    def active_ids(self):
        """The ids to act on: the chosen group, else the ticked rows, else
        None, which means whatever the server has selected."""
        if self.group in self.groups:
            return [eid for eid, _ in self.groups[self.group]]
        ticked = [eid for eid, _ in self.nearby if eid in self.checked]
        return ticked or None


class Models:
    def __init__(self):
        self.roster = Roster()
        self.selection = Selection()
        self.staged = []  # the Prefabs tab's list: name, string, position, rotation, placed
        self.placed = []  # what the Prefabs tab spawned or captured: id, name, string, position, rotation
        self.prefabs = None  # (hash, name) pairs, once fetched
        self.settings = {}  # the server's settings, as last read
