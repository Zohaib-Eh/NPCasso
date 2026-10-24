"""Runs luanti/mods/npcasso/finale.lua against a stand-in for the Luanti API, so the gathering, the slides and the
closing card are exercised without a game window. Skipped when lupa is not installed."""
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

LUA = Path(__file__).resolve().parent.parent / "luanti" / "mods" / "npcasso" / "finale.lua"

SCENE = {"ending": "names_we_buried", "title": "The Names We Buried", "tint": "#1b1410", "slides": [
    {"kind": "narration", "text": "The snow stops at the edge of the square."},
    {"kind": "line", "who": "Elise", "text": "You said what the rest of us would not."},
    {"kind": "title", "text": "The Names We Buried"}]}


class World:
    """A stand-in for core and npcasso. Records what the mod shows and posts."""

    def __init__(self, joined=None):
        self.rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.shown, self.posts, self.closed, self.kicked, self.physics, self.armor = [], [], [], [], [], []
        self.fields, self.joins, self.reply = [], [], SCENE
        self.timeouts = {}
        self.storage = dict(joined or {})
        lua = self.rt
        g = lua.globals()
        player = lua.table(
            is_player=lambda s: True, get_player_name=lambda s: "elise_player",
            set_physics_override=lambda s, t: self.physics.append(dict(t.items())),
            set_armor_groups=lambda s, t: self.armor.append(dict(t.items())))
        store = lua.table(get_string=lambda s, k: self.storage.get(k, ""),
                          set_string=lambda s, k, v: self.storage.__setitem__(k, v))
        g.core = lua.table(
            show_formspec=lambda name, form, fs: self.shown.append((form, fs)),
            close_formspec=lambda name, form: self.closed.append(form),
            disconnect_player=lambda name: self.kicked.append(name),
            get_player_by_name=lambda name: player,
            formspec_escape=lambda s: s,
            register_on_player_receive_fields=lambda fn: self.fields.append(fn),
            register_on_joinplayer=lambda fn: self.joins.append(fn),
            after=lambda t, fn: fn())
        g.npcasso = lua.table(
            store=store, world=lambda: "w", game_time=lambda: 7.5,
            post=lambda path, body, cb=None, timeout=None: self._post(path, cb, timeout))
        self.player = player
        lua.execute(LUA.read_text(encoding="utf-8"))

    def _post(self, path, cb, timeout=None):
        self.posts.append(path)
        self.timeouts[path] = timeout
        if cb:
            cb(self.rt.table_from(self.reply) if isinstance(self.reply, dict) else self.reply)

    def click(self, form, **fields):
        for fn in self.fields:
            fn(self.player, form, self.rt.table(**fields))

    def offer(self, text="They are waiting."):
        self.rt.globals().npcasso.offer_ending("elise_player", text)


def lua_scene(w):
    """The scene as a Lua table, the way core.parse_json would hand it over."""
    def conv(v):
        if isinstance(v, dict):
            return w.rt.table(**{k: conv(x) for k, x in v.items()})
        if isinstance(v, list):
            return w.rt.table_from([conv(x) for x in v])
        return v
    return conv(SCENE)


def test_the_gathering_offers_two_answers():
    w = World()
    w.offer("The village has a truth to carry.")
    form, fs = w.shown[-1]
    assert form == "npcasso:gathering" and "truth to carry" in fs
    assert "Stand with them" in fs and "Walk away" in fs and "allow_close[false]" in fs


def test_walking_away_posts_the_refusal_and_goes_quiet():
    w = World()
    w.offer()
    w.click("npcasso:gathering", walk=True)
    assert w.posts == ["/ending/refuse"] and "npcasso:gathering" in w.closed
    shown = len(w.shown)
    w.offer()
    assert len(w.shown) == shown  # quiet for a while


def test_standing_with_them_plays_the_scene_to_the_card():
    w = World()
    w.offer()
    w.reply = lua_scene(w)
    w.click("npcasso:gathering", stand=True)
    assert w.posts == ["/ending/accept"] and w.timeouts["/ending/accept"] > 30  # three model calls need room
    assert w.storage["ended:elise_player"] == "The Names We Buried"
    assert w.physics == [{"speed": 0, "jump": 0}] and w.armor == [{"immortal": 1}]
    form, fs = w.shown[-1]
    assert form == "npcasso:scene" and "The snow stops" in fs and "Continue" in fs and "Leave" not in fs
    assert "bgcolor[#1b1410f2;true]" in fs
    w.click("npcasso:scene", next=True)
    assert "Elise" in w.shown[-1][1] and "rest of us would not" in w.shown[-1][1]
    w.click("npcasso:scene", next=True)
    form, fs = w.shown[-1]
    assert "The Names We Buried" in fs and "Leave" in fs and "Continue" not in fs
    w.click("npcasso:scene", next=True)  # nothing past the card
    assert w.shown[-1] == (form, fs)
    w.click("npcasso:scene", leave=True)
    assert w.kicked == ["elise_player"]


def test_the_gathering_is_not_offered_again_during_the_scene():
    w = World()
    w.offer()
    w.reply = lua_scene(w)
    w.click("npcasso:gathering", stand=True)
    shown = len(w.shown)
    w.offer()
    assert len(w.shown) == shown


def test_a_failed_accept_closes_the_wait_and_tries_again_later():
    w = World()
    w.reply = None
    w.offer()
    w.click("npcasso:gathering", stand=True)
    assert "npcasso:hold" in w.closed and "ended:elise_player" not in w.storage
    assert w.physics == []


def test_a_finished_world_shows_its_card_on_rejoin():
    w = World({"ended:elise_player": "The Last Departure"})

    for fn in w.joins:
        fn(w.rt.eval("function(...) return {get_player_name=function() return 'elise_player' end, "
                     "is_player=function() return true end, set_physics_override=function() end, "
                     "set_armor_groups=function() end} end")())
    form, fs = w.shown[-1]
    assert form == "npcasso:ended" and "The Last Departure" in fs and "Leave" in fs
    w.click("npcasso:ended", leave=True)
    assert w.kicked == ["elise_player"]
