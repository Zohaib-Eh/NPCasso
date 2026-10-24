"""Runs life.lua's scene logic against stubbed Luanti APIs, to catch runtime errors before a rejoin."""
from lupa.luajit21 import LuaRuntime

STUBS = r"""
local function V(x, y, z) return {x = x, y = y, z = z} end
vector = {}
function vector.new(x, y, z) return V(x, y, z) end
function vector.add(a, b) return V(a.x + b.x, a.y + b.y, a.z + b.z) end
function vector.subtract(a, b) return V(a.x - b.x, a.y - b.y, a.z - b.z) end
function vector.multiply(a, k) return V(a.x * k, a.y * k, a.z * k) end
function vector.length(a) return math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z) end
function vector.distance(a, b) return vector.length(vector.subtract(a, b)) end
function vector.normalize(a) local l = vector.length(a); if l == 0 then return V(0, 0, 0) end return V(a.x / l, a.y / l, a.z / l) end
function vector.round(a) return V(math.floor(a.x + .5), math.floor(a.y + .5), math.floor(a.z + .5)) end
function vector.offset(a, x, y, z) return V(a.x + x, a.y + y, a.z + z) end
function vector.dot(a, b) return a.x * b.x + a.y * b.y + a.z * b.z end

globalsteps = {}
core = {registered_entities = {}, settings = {get_bool = function() return false end}}
function core.register_globalstep(f) table.insert(globalsteps, f) end
function core.register_on_mods_loaded() end
function core.register_on_dignode() end
function core.after() end
function core.get_timeofday() return 0.5 end
function core.get_connected_players() return {player} end
function core.get_player_by_name(n) return player end
function core.get_objects_inside_radius() return {} end
function core.get_node() return {name = "air"} end
function core.find_path() return nil end
core.registered_nodes = {}

local function new_obj(pos)
  local o = {pos = pos, vel = V(0, 0, 0), yaw = 0}
  function o:get_pos() return self.pos end
  function o:get_velocity() return self.vel end
  function o:set_velocity(v) self.vel = v end
  function o:set_yaw(y) self.yaw = y end
  function o:set_animation() end
  function o:get_yaw() return self.yaw end
  return o
end

player = new_obj(V(0, 0, 0))
function player:get_player_name() return "sam" end

npcs = {}
local function add_npc(id, x)
  local e = {npc_id = id, object = new_obj(V(x, 0, 0)), home = V(x, 0, 0), post_yaw = 0}
  npcs[id] = e
  return e
end
add_npc("elise", 6); add_npc("nell", 14); add_npc("pip", 18); add_npc("wren", 22)

npcasso = {npcs = {}, posts = {}, places = {}, moods = {}}
function npcasso.village() return V(0, 0, 0) end
function npcasso.npc_entity(id) return npcs[id] end
function npcasso.each_npc(pos, r) local l = {} for _, e in pairs(npcs) do if vector.distance(e.object.pos, pos) <= r then l[#l + 1] = e end end return l end
function npcasso.stop(e) e.walking = false; e.dest = nil; e.path = nil; e.object.vel = V(0, 0, 0) end
function npcasso.npc_name(id) return id end
function npcasso.post() end
function npcasso.get() end
function npcasso.world() return "w" end
function npcasso.game_time() return 1.0 end
npcasso.ANIM_WALK, npcasso.ANIM_STAND = {x = 1, y = 2}, {x = 3, y = 4}
clock = 1000
os.time = function() return clock end
"""

RUN = r"""
dofile_life()
npcasso.moods = {elise = {mood = "angry", shun = true}, nell = {mood = "cold", shun = false}}
npcasso.play_scene(player, {victim = "elise", victim_mood = "angry", rescuers = {"nell"}, tattlers = {"pip"},
                            guard = "wren"})
assert(npcs.nell.errand == "elise" and npcs.nell.run, "rescuer should run to the victim")
assert(npcs.pip.errand == "wren", "tattler should run to the guard")
assert(npcs.wren.confront == "sam", "guard should confront the player")
for i = 1, 120 do
  clock = clock + 0.25
  for _, e in pairs(npcs) do
    npcasso.life_step(e, 0.25, e.object.pos)
    -- crude physics: move by velocity
    local v = e.object.vel
    e.object.pos = vector.add(e.object.pos, vector.multiply(v, 0.25))
  end
  if i % 8 == 0 then
    print(i * 0.25, "nell->elise", string.format("%.1f", vector.distance(npcs.nell.object.pos, npcs.elise.object.pos)),
      "wren->player", string.format("%.1f", vector.distance(npcs.wren.object.pos, player.pos)),
      "pip->wren", string.format("%.1f", vector.distance(npcs.pip.object.pos, npcs.wren.object.pos)))
  end
end
local d = vector.distance(npcs.wren.object.pos, player.pos)
print("wren distance from player after 15 s:", d)
print("nell distance from elise:", vector.distance(npcs.nell.object.pos, npcs.elise.object.pos))
print("ok")
"""


def main():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(STUBS)
    src = open("luanti/mods/npcasso/life.lua", encoding="utf-8").read()
    lua.globals().dofile_life = lua.eval("function() end")  # placeholder, replaced below
    lua.execute("function dofile_life() end")
    chunk = lua.eval("function(s) return loadstring(s, '@life.lua') end")(src)
    chunk()
    lua.execute(RUN.replace("dofile_life()", ""))


if __name__ == "__main__":
    main()
