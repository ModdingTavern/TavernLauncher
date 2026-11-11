"""The Prefabs tab: a list of objects with their positions and rotations, to
save, load and rebuild, and the group of objects it placed, to move, turn,
drop or delete as one.

Methods of TavernKeeperWindow, which inherits this mixin. This was the
Prefab Loader addon and the Save & Load tab.
"""
import json
import math
import os
import tkinter as tk
from tkinter import filedialog, simpledialog

from tavern_shared.theme import AMBER, BG, BORDER, MONO, MUTED, PARCH, RED, SURF, _btn, _mk_scrollbar, _section_label
from tavern_shared.paths import _tavern_data_dir
from client.core.tavernkeeper.widgets import (
    confirm, entity_name, error_text, form_button, form_entry, form_row, form_text, read_number, say, status_line,
)

STATE_FILE = os.path.join(_tavern_data_dir(), "prefab_collections.json")
PLACED_GROUP = "Prefabs"
# Respawn Point, Discovery Landmark, VR Player Character New.
SKIP_HASHES = (0, 37940, 49582)
MOVE_AXIS = {
    "right": (0, 1.0), "left": (0, -1.0),
    "up": (1, 1.0), "down": (1, -1.0),
    "forward": (2, 1.0), "back": (2, -1.0),
}


def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_state(data):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _num(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _vec(raw, fallback=(0.0, 0.0, 0.0)):
    if isinstance(raw, dict):
        return (
            _num(raw.get("x", raw.get("X")), fallback[0]),
            _num(raw.get("y", raw.get("Y")), fallback[1]),
            _num(raw.get("z", raw.get("Z")), fallback[2]),
        )
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        return (_num(raw[0], fallback[0]), _num(raw[1], fallback[1]), _num(raw[2], fallback[2]))
    return tuple(fallback)


def _fmt_vec(vec):
    return "%.4f,%.4f,%.4f" % (vec[0], vec[1], vec[2])


def _clean_spawn_string(value):
    text = str(value or "").strip()
    if not text:
        return ""
    for line in reversed(text.splitlines()):
        candidate = line.strip().strip('"').strip("'")
        head = candidate.split(",", 1)[0]
        if head.isdigit():
            return candidate
    return ""


def _first_present(raw, *keys):
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return None


def _entry_from_row(raw, index):
    if not isinstance(raw, dict):
        return None
    spawn = _clean_spawn_string(_first_present(raw, "string", "String", "spawn_string"))
    if not spawn:
        return None
    name = str(_first_present(raw, "Name", "name", "label") or "").strip()
    if not name:
        name = "Item %d" % (index + 1)
    position = _first_present(raw, "Position", "position")
    rotation = _first_present(raw, "Rotation", "rotation")
    return {
        "name": name,
        "string": spawn,
        "position": _vec(position),
        "rotation": _vec(rotation),
        "placed": position is not None,
    }


def _read_collection(path):
    """Reads a flat list (this tab's, or the old Save & Load's), Prefabulator's
    {header, prefabs[]}, or a Prefab Loader file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    header = {}
    rows = data
    if isinstance(data, dict):
        header = data.get("header") if isinstance(data.get("header"), dict) else {}
        rows = _first_present(data, "prefabs", "items", "entries")

    if not isinstance(rows, list):
        raise ValueError("No prefab list found in this file.")

    entries = []
    for index, raw in enumerate(rows):
        entry = _entry_from_row(raw, index)
        if entry:
            entries.append(entry)

    if not entries:
        raise ValueError("That file has no usable spawn strings.")

    offset = _vec(header.get("offset"))
    if offset != (0.0, 0.0, 0.0):
        for entry in entries:
            entry["position"] = tuple(entry["position"][i] + offset[i] for i in range(3))
    return header, entries


def _write_collection(path, entries):
    rows = []
    for entry in entries:
        row = {"name": entry["name"], "string": entry["string"]}
        if entry["placed"]:
            position = entry["position"]
            rotation = entry["rotation"]
            row["position"] = {"x": position[0], "y": position[1], "z": position[2]}
            row["rotation"] = {"x": rotation[0], "y": rotation[1], "z": rotation[2]}
        rows.append(row)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _bounds_low(positions):
    if not positions:
        return (0.0, 0.0, 0.0)
    return (
        min(p[0] for p in positions),
        min(p[1] for p in positions),
        min(p[2] for p in positions),
    )


def _centroid(positions):
    if not positions:
        return (0.0, 0.0, 0.0)
    count = float(len(positions))
    return (
        sum(p[0] for p in positions) / count,
        sum(p[1] for p in positions) / count,
        sum(p[2] for p in positions) / count,
    )


def _lowest_corner(entries):
    return _bounds_low([e["position"] for e in entries if e["placed"]])


def _norm_deg(value):
    value = math.fmod(_num(value), 360.0)
    if value < 0.0:
        value += 360.0
    return 0.0 if abs(value - 360.0) < 1e-9 else value


def _quat_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by + ay * bw + az * bx - ax * bz,
        aw * bz + az * bw + ax * by - ay * bx,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _euler_to_quat(euler):
    # Unity's Quaternion.Euler(x, y, z) composes as Ry * Rx * Rz.
    hx = math.radians(_num(euler[0])) * 0.5
    hy = math.radians(_num(euler[1])) * 0.5
    hz = math.radians(_num(euler[2])) * 0.5
    qx = (math.sin(hx), 0.0, 0.0, math.cos(hx))
    qy = (0.0, math.sin(hy), 0.0, math.cos(hy))
    qz = (0.0, 0.0, math.sin(hz), math.cos(hz))
    return _quat_mul(_quat_mul(qy, qx), qz)


def _quat_to_euler(quat):
    x, y, z, w = quat
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length > 0.0:
        x, y, z, w = x / length, y / length, z / length, w / length

    m12 = max(-1.0, min(1.0, 2.0 * (y * z - w * x)))
    pitch = math.asin(-m12)
    if abs(m12) < 0.9999995:
        roll = math.atan2(2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z))
        yaw = math.atan2(2.0 * (x * z + w * y), 1.0 - 2.0 * (x * x + y * y))
    else:
        # Pitch is +-90, so yaw and roll describe the same turn. Fold it into yaw.
        roll = 0.0
        yaw = math.atan2(-2.0 * (x * z - w * y), 1.0 - 2.0 * (y * y + z * z))
    return (
        _norm_deg(math.degrees(pitch)),
        _norm_deg(math.degrees(yaw)),
        _norm_deg(math.degrees(roll)),
    )


def _yaw_rotation(euler, degrees):
    # `select rotate yaw` right-multiplies about the object's own up axis, which
    # is wrong for a group of tilted items. A world turn is the left-multiply
    # below, which the console cannot do -- hence `rotate exact`.
    half = math.radians(_num(degrees)) * 0.5
    world = (0.0, math.sin(half), 0.0, math.cos(half))
    return _quat_to_euler(_quat_mul(world, _euler_to_quat(euler)))


def _yaw_position(position, pivot, degrees):
    radians = math.radians(_num(degrees))
    cos = math.cos(radians)
    sin = math.sin(radians)
    dx = position[0] - pivot[0]
    dz = position[2] - pivot[2]
    return (
        pivot[0] + dx * cos + dz * sin,
        position[1],
        pivot[2] - dx * sin + dz * cos,
    )


def _moved_position(position, direction, amount):
    if position is None or direction not in MOVE_AXIS:
        return position
    index, sign = MOVE_AXIS[direction]
    shifted = list(position)
    shifted[index] += sign * amount
    return tuple(shifted)


def _entity_info(value):
    if not isinstance(value, dict) or value.get("Position") is None:
        return None
    return {
        "position": _vec(value.get("Position")),
        "rotation": _vec(value.get("Rotation")),
        "name": entity_name(value.get("Name") or "").strip(),
        "id": int(_num(value.get("Identifier"), 0)),
        "hash": int(_num(value.get("PrefabHash"), 0)),
        "parent": int(_num(value.get("ChunkingParent"), 0)),
    }


def _spawned_id(value):
    rows = value if isinstance(value, list) else [value]
    for row in rows:
        if isinstance(row, dict) and _num(row.get("Identifier"), 0):
            return int(row["Identifier"])
    return 0


def _plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


class PrefabsTabMixin:
    @staticmethod
    def _clean_spawn_string(rs):
        """The spawn string in a select tostring reply, or None."""
        return _clean_spawn_string(rs) or None

    def _build_prefabs_tab(self, parent):
        self._pf_running = False
        self._pf_cancel = False
        self._pf_source = ""

        tk.Label(parent, text="Objects with their positions and rotations: save them, load them, rebuild them.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(10, 2))

        _section_label(parent, "LIST")
        row = form_row(parent)
        form_button(row, "📂 Open File…", self._on_pf_open, "primary")
        form_button(row, "💾 Save File…", self._on_pf_save)
        self._pf_count = tk.Label(row, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8))
        self._pf_count.pack(side="right")
        row = form_row(parent)
        form_button(row, "+ Add Selection", self._on_pf_add_selection, "primary")
        form_button(row, "Capture Nearby", self._on_pf_capture)
        form_text(row, "Diameter:")
        self.v_pf_diameter = tk.StringVar(value="10")
        form_entry(row, self.v_pf_diameter, 5)
        self._pf_source_label = tk.Label(parent, text="", bg=BG, fg=PARCH, font=MONO, anchor="w", justify="left")
        self._pf_source_label.pack(fill="x", padx=22)

        box = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        box.pack(fill="both", expand=True, padx=20, pady=(2, 4))
        self._pf_listbox = tk.Listbox(box, bg=SURF, fg=PARCH, font=MONO, height=10, width=50,
                                      selectbackground=AMBER, selectforeground=BG, activestyle="none",
                                      highlightthickness=0, relief="flat", bd=0)
        scroll = _mk_scrollbar(box, self._pf_listbox.yview)
        scroll.pack(side="right", fill="y")
        self._pf_listbox.config(yscrollcommand=scroll.set)
        self._pf_listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self._pf_listbox.bind("<Double-Button-1>", self._on_pf_rename)
        row = form_row(parent)
        form_button(row, "− Remove", self._on_pf_remove, "danger")
        form_button(row, "Clear List", self._on_pf_clear, "danger")
        form_text(row, "Double-click a row to rename it.")

        _section_label(parent, "REBUILD")
        row = form_row(parent)
        self.v_pf_mode = tk.StringVar(value="exact")
        for value, text in (("exact", "Where they were"), ("player", "At the target player")):
            tk.Radiobutton(row, text=text, value=value, variable=self.v_pf_mode, bg=BG, fg=PARCH,
                           selectcolor=SURF, activebackground=BG, activeforeground=AMBER, highlightthickness=0,
                           bd=0, font=("Segoe UI", 9)).pack(side="left", padx=(0, 14))
        row = form_row(parent)
        form_text(row, "Offset X")
        self.v_pf_offset_x = tk.StringVar(value="0")
        form_entry(row, self.v_pf_offset_x, 6)
        form_text(row, "Y")
        self.v_pf_offset_y = tk.StringVar(value="0")
        form_entry(row, self.v_pf_offset_y, 6)
        form_text(row, "Z")
        self.v_pf_offset_z = tk.StringVar(value="0")
        form_entry(row, self.v_pf_offset_z, 6)
        row = form_row(parent)
        form_button(row, "▶ Rebuild", self._on_pf_rebuild, "success")
        form_button(row, "■ Stop", self._on_pf_stop)
        self._say_prefabs = status_line(parent)

        _section_label(parent, "PLACED GROUP")
        row = form_row(parent)
        self._pf_placed_label = tk.Label(row, text="", bg=BG, fg=PARCH, font=("Segoe UI", 9))
        self._pf_placed_label.pack(side="left", padx=(0, 10))
        form_button(row, "⟳ From World", self._on_pf_from_world)
        form_button(row, "Untrack", self._on_pf_untrack)
        form_button(row, "✖ Delete All", self._on_pf_delete_all, "danger")
        row = form_row(parent)
        form_text(row, "Move")
        self.v_pf_step = tk.StringVar(value="1")
        form_entry(row, self.v_pf_step, 5)
        for direction, text in (("left", "◀"), ("right", "▶"), ("down", "▼"), ("up", "▲"),
                                ("back", "Back"), ("forward", "Fwd")):
            _btn(row, text, lambda d=direction: self._on_pf_move(d), font=("Segoe UI", 9), pady=5,
                 padx=8).pack(side="left", padx=(0, 3))
        form_button(row, "⤓ Snap All", self._on_pf_snap)
        row = form_row(parent)
        form_text(row, "Turn")
        self.v_pf_angle = tk.StringVar(value="90")
        form_entry(row, self.v_pf_angle, 5)
        form_button(row, "⟲ Turn Left", lambda: self._on_pf_turn(-1))
        form_button(row, "⟳ Turn Right", lambda: self._on_pf_turn(1))
        form_text(row, "around")
        self.v_pf_pivot = tk.StringVar(value="centre")
        for value, text in (("centre", "its centre"), ("corner", "its lowest corner")):
            tk.Radiobutton(row, text=text, value=value, variable=self.v_pf_pivot, bg=BG, fg=PARCH,
                           selectcolor=SURF, activebackground=BG, activeforeground=AMBER, highlightthickness=0,
                           bd=0, font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        tk.Label(parent, text=f"The Build tab's move pad works on this group too: pick the {PLACED_GROUP} group there.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=(0, 8))

        self._pf_show_list()
        self._pf_show_placed()
        remembered = _load_state().get("last_file", "")
        if remembered and os.path.isfile(remembered):
            self._pf_load_path(remembered, announce=False)

    # The list

    def _pf_show_list(self):
        self._pf_listbox.delete(0, "end")
        entries = self.models.staged
        for entry in entries:
            if entry["placed"]:
                where = "%9.1f %9.1f %9.1f" % entry["position"]
            else:
                where = "    no saved position"
            mark = "!" if "|" not in entry["string"] else " "
            self._pf_listbox.insert("end", "%s%-32s %s" % (mark, entry["name"][:32], where))
        placed = sum(1 for e in entries if e["placed"])
        self._pf_count.config(text=f"{_plural(len(entries), 'item')}, {placed} with a position" if entries else "empty")

    def _pf_adopt(self, entries, source):
        self.models.staged = entries
        self._pf_source = source
        self._pf_source_label.config(text=source)
        self._pf_show_list()
        bare = sum(1 for e in entries if "|" not in e["string"])
        if bare:
            say(self._say_prefabs, f"{_plural(bare, 'row')} (marked !) have no component table after a |, "
                                   "so the game may not spawn them. Capturing them again fixes that.", AMBER)

    def _pf_load_path(self, path, announce=True):
        try:
            header, entries = _read_collection(path)
        except Exception as exc:
            say(self._say_prefabs, f"Couldn't read {os.path.basename(path)}: {exc}", RED)
            return False
        bits = [os.path.basename(path)]
        if header.get("player"):
            bits.append("saved by %s" % header["player"])
        if header.get("timestamp"):
            bits.append(str(header["timestamp"]))
        say(self._say_prefabs, "")
        self._pf_adopt(entries, "  ·  ".join(bits))
        state = _load_state()
        state["last_file"] = path
        _save_state(state)
        if announce and self._say_prefabs.cget("text") == "":
            say(self._say_prefabs, f"Opened {os.path.basename(path)}: {_plural(len(entries), 'item')}.")
        return True

    def _on_pf_open(self):
        path = filedialog.askopenfilename(parent=self, title="Open prefab list",
                                          filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self._pf_load_path(path)

    def _on_pf_save(self):
        if not self.models.staged:
            say(self._say_prefabs, "The list is empty.", RED)
            return
        path = filedialog.asksaveasfilename(parent=self, title="Save prefab list", defaultextension=".json",
                                            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            _write_collection(path, self.models.staged)
        except Exception as exc:
            say(self._say_prefabs, f"Couldn't save: {exc}", RED)
            return
        say(self._say_prefabs, f"Saved {_plural(len(self.models.staged), 'item')} to {os.path.basename(path)}.")

    def _on_pf_rename(self, event=None):
        sel = self._pf_listbox.curselection()
        if not sel:
            return
        entry = self.models.staged[sel[0]]
        name = simpledialog.askstring("Rename", "New name:", initialvalue=entry["name"], parent=self)
        if name and name.strip():
            entry["name"] = name.strip()
            self._pf_show_list()
            self._pf_listbox.selection_set(sel[0])

    def _on_pf_remove(self):
        sel = self._pf_listbox.curselection()
        if not sel:
            say(self._say_prefabs, "Pick a row first.", RED)
            return
        entry = self.models.staged[sel[0]]
        if confirm(self, "Remove", f"Remove {entry['name']} from the list?"):
            del self.models.staged[sel[0]]
            self._pf_show_list()

    def _on_pf_clear(self):
        if self.models.staged and confirm(self, "Clear the list",
                                          f"Clear all {_plural(len(self.models.staged), 'item')}? "
                                          "Anything not saved to a file is lost."):
            self._pf_adopt([], "")

    # Jobs: one item at a time, stopping at the first failure

    def _pf_busy(self):
        if self._pf_running:
            say(self._say_prefabs, "Wait for the current job to finish, or press Stop.", RED)
        return self._pf_running

    def _on_pf_stop(self):
        if self._pf_running:
            self._pf_cancel = True
            say(self._say_prefabs, "Stopping after this item...", AMBER)

    def _pf_job(self, label, items, action, done):
        """action(item, advance, fail) runs one item's commands, then calls
        advance(), or fail(result, what) to stop the job with the server's reply.
        done(completed, ok) always runs at the end."""
        total = len(items)
        state = {"index": 0}
        self._pf_running = True
        self._pf_cancel = False

        def finish(ok, text, color):
            self._pf_running = False
            say(self._say_prefabs, text, color)
            done(state["index"], ok)

        def step():
            if self._pf_cancel:
                finish(False, f"{label} stopped at {state['index']} of {total}.", AMBER)
            elif state["index"] >= total:
                finish(True, "", MUTED)
            else:
                say(self._say_prefabs, f"{label} {state['index'] + 1} of {total}...", AMBER)
                action(items[state["index"]], advance, fail)

        def advance():
            state["index"] += 1
            self.after(1, step)

        def fail(result, what):
            if result.timed_out:
                why = "no answer from the server"
            elif result.error:
                why = error_text(result.error)
            else:
                why = result.text or "the server said nothing"
            finish(False, f"{what}: {why}. Stopped at {state['index'] + 1} of {total}.", RED)
            self._append_log(f"[Prefabs] {what}: {why}\n", "err")

        step()

    def _pf_run(self, cmd, then, fail, what):
        """One command of a job: then(result) if it worked, else fail."""
        self._run_command(cmd, lambda r: then(r) if r.ok else fail(r, what), quiet=True)

    def _pf_ready_target(self):
        if self._pf_busy():
            return None
        return self._current_target()

    # Adding

    def _on_pf_add_selection(self):
        if self._pf_busy():
            return
        ids = self.api.selection or [None]
        added = []

        def action(eid, advance, fail):
            def exported(info, result):
                spawn = _clean_spawn_string(result.text)
                if not spawn:
                    fail(result, "Couldn't get a spawn string")
                    return
                added.append({"name": info["name"] or "Item %d" % (len(self.models.staged) + len(added) + 1),
                              "string": spawn, "position": info["position"], "rotation": info["rotation"],
                              "placed": True})
                advance()

            def inspected(result):
                info = _entity_info(result.value)
                if info is None:
                    fail(result, "Couldn't read the object")
                    return
                self._pf_run("select tostring", lambda r: exported(info, r), fail, "Couldn't get a spawn string")

            if eid is None:
                self._pf_run("select get", inspected, fail, "Nothing is selected")
            else:
                self._pf_run(f"select {eid}", lambda r: self._pf_run("select get", inspected, fail, f"Couldn't read {eid}"),
                             fail, f"Couldn't select {eid}")

        def done(completed, ok):
            if added:
                self.models.staged.extend(added)
                self._pf_show_list()
            if ok:
                say(self._say_prefabs, f"Added {_plural(len(added), 'item')}.")
        self._pf_job("Adding", ids, action, done)

    def _on_pf_capture(self):
        target = self._pf_ready_target()
        if not target:
            return
        diameter = read_number(self.v_pf_diameter, self._say_prefabs, "the diameter")
        if diameter is None:
            return
        if diameter <= 0:
            say(self._say_prefabs, "The diameter has to be more than 0.", RED)
            return
        collected, placed = [], []

        def found(result):
            rows = result.value if result.ok and isinstance(result.value, list) else None
            if rows is None:
                self._answer_on(self._say_prefabs, "")(result)
                return
            candidates = [int(r["Identifier"]) for r in rows if isinstance(r, dict) and r.get("Identifier")]
            if not candidates:
                say(self._say_prefabs, "Nothing found nearby.", AMBER)
                return

            def action(eid, advance, fail):
                def exported(info, r):
                    spawn = _clean_spawn_string(r.text)
                    if spawn:
                        name = info["name"] or "Item %d" % (len(collected) + 1)
                        collected.append({"name": name, "string": spawn, "position": info["position"],
                                          "rotation": info["rotation"], "placed": True})
                        placed.append({"id": eid, "name": name, "string": spawn,
                                       "position": info["position"], "rotation": info["rotation"]})
                    advance()

                def inspected(r):
                    info = _entity_info(r.value) if r.ok else None
                    # Docked children ride along inside the parent's spawn string.
                    if info is None or info["hash"] in SKIP_HASHES or info["parent"]:
                        advance()
                        return
                    self._pf_run(f"select {eid}", lambda _: self._pf_run(
                        "select tostring", lambda r2: exported(info, r2), fail, f"Couldn't copy {info['name']}"),
                        fail, f"Couldn't select {info['name']}")

                self._run_command(f"select get {eid}", inspected, quiet=True)

            def done(completed, ok):
                if collected:
                    self._pf_adopt(collected, f"captured around {target}")
                    self._pf_track(placed)
                if ok:
                    say(self._say_prefabs, f"Captured {_plural(len(collected), 'item')} around {target}."
                        if collected else "Nothing worth capturing.", MUTED if collected else AMBER)
            self._pf_job("Capturing", candidates, action, done)

        self._run_command(f"select find {self._q_target(target)} {diameter:g}", found, quiet=True)

    # Rebuilding

    def _on_pf_rebuild(self):
        entries = list(self.models.staged)
        if not entries:
            say(self._say_prefabs, "The list is empty. Open a file or capture something first.", RED)
            return
        target = self._pf_ready_target()
        if not target:
            return
        nudge = []
        for var, axis in ((self.v_pf_offset_x, "X"), (self.v_pf_offset_y, "Y"), (self.v_pf_offset_z, "Z")):
            value = read_number(var, self._say_prefabs, f"the {axis} offset")
            if value is None:
                return
            nudge.append(value)
        anchored = self.v_pf_mode.get() == "player"
        base = _lowest_corner(entries) if anchored else (0.0, 0.0, 0.0)
        state = {"anchor": None}
        placed = []
        q = self._q_target(target)

        def action(entry, advance, fail):
            what = f"{entry['name']} did not spawn"

            def done(eid, position, rotation):
                placed.append({"id": eid, "name": entry["name"], "string": entry["string"],
                               "position": position, "rotation": rotation})
                advance()

            def place(eid):
                anchor = state["anchor"] or (0.0, 0.0, 0.0)
                position = tuple(entry["position"][i] - base[i] + anchor[i] + nudge[i] for i in range(3))
                self._pf_run(f"select {eid}", lambda _: self._pf_run(
                    f"select rotate exact {_fmt_vec(entry['rotation'])}", lambda _: self._pf_run(
                        f"select move exact {_fmt_vec(position)}", lambda _: done(eid, position, entry["rotation"]),
                        fail, f"Couldn't move {entry['name']}"),
                    fail, f"Couldn't turn {entry['name']}"),
                    fail, f"Couldn't select {entry['name']}")

            def read_anchor(eid, result):
                info = _entity_info(result.value)
                if info is None:
                    fail(result, "Couldn't read where the first item landed")
                    return
                state["anchor"] = info["position"]
                place(eid)

            def spawned(result):
                eid = _spawned_id(result.value)
                if not eid:
                    fail(result, what)
                elif not entry["placed"]:
                    done(eid, None, None)
                elif anchored and state["anchor"] is None:
                    self._pf_run(f"select get {eid}", lambda r: read_anchor(eid, r), fail,
                                 "Couldn't read where the first item landed")
                else:
                    place(eid)

            if entry["placed"] or anchored:
                self._pf_run(f"spawn string {q} {self._q(entry['string'])}", spawned, fail, what)
            else:
                self._pf_run(f"spawn string-raw {self._q(entry['string'])}", spawned, fail, what)

        def finished(completed, ok):
            self._pf_track(placed)
            if ok:
                say(self._say_prefabs, f"Rebuilt {_plural(len(placed), 'item')}.", MUTED)
        self._pf_job("Rebuilding", entries, action, finished)

    # The placed group

    def _pf_track(self, rows):
        self.models.placed.extend(rows)
        self._pf_show_placed()

    def _pf_show_placed(self):
        placed = self.models.placed
        self._pf_placed_label.config(text=f"{_plural(len(placed), 'item')} placed" if placed else "Nothing placed yet")
        selection = self.models.selection
        if placed:
            selection.groups[PLACED_GROUP] = [(r["id"], r["name"]) for r in placed]
        else:
            selection.groups.pop(PLACED_GROUP, None)
            if selection.group == PLACED_GROUP:
                selection.group = None
        if hasattr(self, "_group_combo"):
            self._group_combo["values"] = ["(none)"] + list(selection.groups)
            if self._group_combo_var.get() not in selection.groups:
                self._group_combo_var.set("(none)")

    def _pf_ready_group(self):
        if self._pf_busy():
            return False
        if not self.models.placed:
            say(self._say_prefabs, "Nothing placed yet. Rebuild or capture first.", RED)
            return False
        return True

    def _pf_read_placed(self, then):
        """Re-reads every placed item, dropping the ones that are gone."""
        rows = list(self.models.placed)
        alive = []

        def action(row, advance, fail):
            def got(result):
                info = _entity_info(result.value) if result.ok else None
                if info is not None:
                    row["position"], row["rotation"] = info["position"], info["rotation"]
                    alive.append(row)
                advance()
            self._run_command(f"select get {row['id']}", got, quiet=True)

        def done(completed, ok):
            if ok:
                self.models.placed = alive
                self._pf_show_placed()
                then(len(rows) - len(alive))
        self._pf_job("Reading", rows, action, done)

    def _on_pf_from_world(self):
        if not self._pf_ready_group():
            return

        def then(lost):
            rows = self.models.placed
            self._pf_adopt([{"name": r["name"], "string": r["string"], "position": r["position"],
                             "rotation": r["rotation"], "placed": True} for r in rows],
                           f"read from the world ({_plural(len(rows), 'item')})")
            say(self._say_prefabs, f"The list shows {_plural(len(rows), 'item')} as they stand now."
                + (f" {lost} are gone." if lost else "") + " Save File to keep it.")
        self._pf_read_placed(then)

    def _on_pf_untrack(self):
        count = len(self.models.placed)
        if count and not self._pf_busy() and confirm(
                self, "Untrack", f"Forget the {_plural(count, 'placed item')}? They stay in the world."):
            self.models.placed = []
            self._pf_show_placed()
            say(self._say_prefabs, "")

    def _on_pf_delete_all(self):
        if not self._pf_ready_group():
            return
        rows = list(self.models.placed)
        if not confirm(self, "Delete the group", f"Destroy all {_plural(len(rows), 'placed item')}? This can't be undone."):
            return

        def action(row, advance, fail):
            self._pf_run(f"wacky destroy {row['id']}", lambda _: advance(), fail, f"Couldn't destroy {row['name']}")

        def done(completed, ok):
            gone = [r["id"] for r in rows[:completed]]
            self.models.selection.forget(gone)
            self.models.placed = rows[completed:]
            self._pf_show_placed()
            if ok:
                say(self._say_prefabs, f"Destroyed {_plural(completed, 'item')}.")
        self._pf_job("Deleting", rows, action, done)

    def _pf_each_selected(self, label, command_for, then_row, done_text):
        rows = list(self.models.placed)

        def action(row, advance, fail):
            self._pf_run(f"select {row['id']}", lambda _: self._pf_run(
                command_for(row), lambda _: (then_row(row), advance()), fail, f"Couldn't change {row['name']}"),
                fail, f"Couldn't select {row['name']} (gone?)")

        def done(completed, ok):
            if ok:
                say(self._say_prefabs, done_text)
        self._pf_job(label, rows, action, done)

    def _on_pf_move(self, direction):
        if not self._pf_ready_group():
            return
        amount = read_number(self.v_pf_step, self._say_prefabs, "the step")
        if amount is None:
            return
        if amount <= 0:
            say(self._say_prefabs, "The step has to be more than 0.", RED)
            return

        def moved(row):
            row["position"] = _moved_position(row["position"], direction, amount)
        self._pf_each_selected("Moving", lambda row: f"select move {direction} {amount:g}", moved,
                               f"Moved the group {direction} {amount:g}.")

    def _on_pf_snap(self):
        if self._pf_ready_group():
            self._pf_each_selected("Snapping", lambda row: "select snap-ground", lambda row: None,
                                   "Dropped the group to the ground.")

    def _on_pf_turn(self, sign):
        if not self._pf_ready_group():
            return
        degrees = read_number(self.v_pf_angle, self._say_prefabs, "the angle")
        if not degrees:
            return
        degrees *= sign

        # Read first: items may have moved since, and a stale pivot swings the group somewhere wrong.
        def then(lost):
            rows = [r for r in self.models.placed if r["position"] is not None]
            if not rows:
                return
            positions = [r["position"] for r in rows]
            pivot = _bounds_low(positions) if self.v_pf_pivot.get() == "corner" else _centroid(positions)

            def action(row, advance, fail):
                position = _yaw_position(row["position"], pivot, degrees)
                rotation = _yaw_rotation(row["rotation"] or (0.0, 0.0, 0.0), degrees)

                def turned(_):
                    row["position"], row["rotation"] = position, rotation
                    advance()
                self._pf_run(f"select {row['id']}", lambda _: self._pf_run(
                    f"select rotate exact {_fmt_vec(rotation)}", lambda _: self._pf_run(
                        f"select move exact {_fmt_vec(position)}", turned, fail, f"Couldn't move {row['name']}"),
                    fail, f"Couldn't turn {row['name']}"),
                    fail, f"Couldn't select {row['name']}")

            def done(completed, ok):
                if ok:
                    say(self._say_prefabs, f"Turned the group {degrees:g} degrees around {_fmt_vec(pivot)}.")
            self.after(1, lambda: self._pf_job("Turning", rows, action, done))
        self._pf_read_placed(then)
