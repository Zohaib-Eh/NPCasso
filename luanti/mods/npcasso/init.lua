-- NPCasso: NPCs that remember. All state and rules live in the backend; this mod detects actions,
-- decides who witnessed them, and shows dialogue and notices. No secrets, no LLM logic here.

local http = core.request_http_api()
if not http then
	core.log("error", "[npcasso] HTTP disabled. Add 'secure.http_mods = npcasso' to minetest.conf")
end

local BASE = core.settings:get("npcasso.backend_url") or "http://127.0.0.1:8000"
core.log("action", "[npcasso] loaded, backend " .. BASE .. (http and "" or " (HTTP DISABLED)"))
local WITNESS_RANGE, WITNESS_COS, WORK_RANGE, TICK_SECONDS = 10, 0.5, 8, 30
local ANVILS = {"cottages:anvil", "npcasso:anvil"}

npcasso = {npcs = {}}          -- id -> {name, role, skin, work_block}, from GET /npcs
local talk = {}                -- player name -> {npc, thread, history = {}, sent = 0, busy = false}

-- HTTP ---------------------------------------------------------------------------------------------

local function fetch(method, path, body, cb)
	if not http then return cb(nil) end
	http.fetch({url = BASE .. path, method = method, timeout = 30,
		data = body and core.write_json(body) or nil,
		extra_headers = body and {"Content-Type: application/json"} or nil},
		function(res)
			if res.succeeded and res.code == 200 then
				cb(core.parse_json(res.data))
			else
				core.log("warning", "[npcasso] " .. method .. " " .. path .. " failed: " .. tostring(res.code))
				cb(nil)
			end
		end)
end

function npcasso.post(path, body, cb) fetch("POST", path, body, cb or function() end) end
function npcasso.get(path, cb) fetch("GET", path, nil, cb) end

function npcasso.world() return core.get_worldpath():match("([^/\\]+)$") end
function npcasso.game_time() return core.get_day_count() + core.get_timeofday() end

local function npc_name(id) return (npcasso.npcs[id] or {}).name or id end

-- Notices and responses ----------------------------------------------------------------------------

function npcasso.notice(player, text)
	local id = player:hud_add({type = "text", position = {x = 0.5, y = 0.18}, alignment = {x = 0, y = 0},
		text = text, number = 0xFFE7A8, scale = {x = 100, y = 100}, size = {x = 2}})
	core.after(4, function()
		if player:is_player() then player:hud_remove(id) end
	end)
end

-- Shows notices/shouts and hands out items from any backend response.
local function apply(name, out)
	local player = core.get_player_by_name(name)
	if not player or not out then return end
	for _, s in ipairs(out.shouts or {}) do
		core.chat_send_player(name, core.colorize("#FFD27F", "<" .. npc_name(s.npc_id) .. "> ") .. s.text)
	end
	for i, n in ipairs(out.notices or {}) do
		core.after((i - 1) * 1.5, function() if player:is_player() then npcasso.notice(player, n) end end)
	end
	for _, g in ipairs(out.give or {}) do
		local left = player:get_inventory():add_item("main", ItemStack(g.item .. " " .. g.count))
		if not left:is_empty() then core.add_item(player:get_pos(), left) end
	end
end

function npcasso.event(player, type, target, details, witnesses)
	local name = player:get_player_name()
	npcasso.post("/event", {world = npcasso.world(), player = name, type = type, target = target,
		details = details or {}, witnesses = witnesses or {}, game_time = npcasso.game_time()},
		function(out) apply(name, out) end)
end

-- NPC entities and witnesses -----------------------------------------------------------------------

local function each_npc(pos, radius)
	local list = {}
	for _, obj in ipairs(core.get_objects_inside_radius(pos, radius)) do
		local e = obj:get_luaentity()
		if e and e.name == "npcasso:npc" and e.npc_id then table.insert(list, e) end
	end
	return list
end

local function find_npc(id, pos, radius)
	for _, e in ipairs(each_npc(pos, radius)) do
		if e.npc_id == id then return e end
	end
end

-- An NPC witnesses something if it is close, has line of sight, and faces roughly toward it.
function npcasso.witnesses(pos)
	local eye = vector.offset(pos, 0, 1.5, 0)
	local seen = {}
	for _, e in ipairs(each_npc(pos, WITNESS_RANGE)) do
		local npos = e.object:get_pos()
		local neye = vector.offset(npos, 0, 1.5, 0)
		local dir = vector.normalize({x = pos.x - npos.x, y = 0, z = pos.z - npos.z})
		local yaw = e.object:get_yaw()
		local face = {x = -math.sin(yaw), y = 0, z = math.cos(yaw)}
		local close = vector.distance(pos, npos) < 1.5
		if core.line_of_sight(neye, eye) and (close or vector.dot(dir, face) > WITNESS_COS) then
			table.insert(seen, e.npc_id)
		end
	end
	return seen
end

local function set_look(self)
	local info = npcasso.npcs[self.npc_id] or {}
	self.object:set_properties({
		nametag = (info.name or tostring(self.npc_id)) .. " · " .. (info.role or ""),
		nametag_color = "#FFFFFF",
		textures = {info.skin or "character.png"},
	})
end

local ANIM_STAND, ANIM_WALK = {x = 0, y = 79}, {x = 168, y = 187}
local WANDER, WALK_SPEED, GREET_RANGE, GREET_COOLDOWN = 3, 1.2, 5, 180

local function stop(self)
	local v = self.object:get_velocity()
	self.object:set_velocity({x = 0, y = v.y, z = 0})
	if self.target then self.object:set_animation(ANIM_STAND, 30, 0) end
	self.target = nil
end

core.register_entity("npcasso:npc", {
	initial_properties = {
		physical = true, collide_with_objects = true, visual = "mesh", mesh = "character.b3d",
		textures = {"character.png"}, visual_size = {x = 1, y = 1},
		collisionbox = {-0.3, 0.0, -0.3, 0.3, 1.7, 0.3}, stepheight = 0.6, static_save = true,
	},
	on_activate = function(self, staticdata)
		local d = core.deserialize(staticdata) or {}
		self.npc_id, self.post_yaw = d.npc_id, d.yaw or 0
		self.home = d.home or vector.round(self.object:get_pos())
		self.greeted, self.rest = {}, math.random(2, 6)
		self.object:set_armor_groups({immortal = 1})
		self.object:set_acceleration({x = 0, y = -9.81, z = 0})
		self.object:set_yaw(self.post_yaw)
		self.object:set_animation(ANIM_STAND, 30, 0)
		set_look(self)
	end,
	get_staticdata = function(self)
		return core.serialize({npc_id = self.npc_id, yaw = self.post_yaw, home = self.home})
	end,
	on_step = function(self, dtime)
		self.timer = (self.timer or 0) + dtime
		if self.timer < 0.25 then return end
		local dt = self.timer
		self.timer = 0
		local pos = self.object:get_pos()

		-- Talking: stop and face the player.
		for name, t in pairs(talk) do
			local p = core.get_player_by_name(name)
			if t.npc == self.npc_id and p then
				stop(self)
				local d = vector.subtract(p:get_pos(), pos)
				self.object:set_yaw(math.atan2(-d.x, d.z))
				return
			end
		end

		-- Greet players who walk up, once every few minutes each.
		for _, p in ipairs(core.get_connected_players()) do
			local name = p:get_player_name()
			if vector.distance(p:get_pos(), pos) < GREET_RANGE and os.time() - (self.greeted[name] or 0) > GREET_COOLDOWN then
				self.greeted[name] = os.time()
				stop(self)
				local d = vector.subtract(p:get_pos(), pos)
				self.object:set_yaw(math.atan2(-d.x, d.z))
				self.rest = 6
				npcasso.post("/greet", {world = npcasso.world(), player = name, npc_id = self.npc_id,
					thread_id = npcasso.world() .. ":" .. name .. ":" .. self.npc_id .. ":greet:" .. os.time(),
					game_time = npcasso.game_time()}, function(out)
					if out and out.reply ~= "" and not talk[name] then
						core.chat_send_player(name, core.colorize("#FFD27F", "<" .. npc_name(self.npc_id) .. "> ") .. out.reply)
					end
				end)
			end
		end

		-- Wander: walk to a spot near home, rest, repeat. Resting at home faces the post direction.
		if self.target then
			local d = vector.subtract(self.target, pos)
			d.y = 0
			if vector.length(d) < 0.4 or (self.walked or 0) > 8 then
				stop(self)
				if vector.distance(self.target, self.home) < 0.5 then self.object:set_yaw(self.post_yaw) end
				self.target, self.rest = nil, math.random(4, 10)
			else
				local v = vector.multiply(vector.normalize(d), WALK_SPEED)
				self.object:set_velocity({x = v.x, y = self.object:get_velocity().y, z = v.z})
				self.object:set_yaw(math.atan2(-d.x, d.z))
				self.walked = (self.walked or 0) + dt
			end
		else
			self.rest = self.rest - dt
			if self.rest <= 0 then
				self.target = math.random() < 0.4 and self.home
					or vector.offset(self.home, math.random(-WANDER, WANDER), 0, math.random(-WANDER, WANDER))
				self.walked = 0
				self.object:set_animation(ANIM_WALK, 30, 0)
			end
		end
	end,
	on_rightclick = function(self, clicker)
		npcasso.open_talk(clicker, self.npc_id)
	end,
	on_punch = function(self, puncher)
		if puncher and puncher:is_player() then
			local w = npcasso.witnesses(puncher:get_pos())
			table.insert(w, self.npc_id)
			npcasso.event(puncher, "hit_npc", self.npc_id, {}, w)
		end
		return true
	end,
})

-- Dialogue -----------------------------------------------------------------------------------------

local function show_talk(name)
	local t = talk[name]
	if not t then return end
	local lines = {}
	for i = math.max(1, #t.history - 7), #t.history do
		table.insert(lines, core.formspec_escape(t.history[i]))
	end
	if t.busy then table.insert(lines, core.formspec_escape(npc_name(t.npc) .. " is thinking...")) end
	local info = npcasso.npcs[t.npc] or {}
	local fs = "formspec_version[6]size[12,9]" ..
		"label[0.4,0.5;" .. core.formspec_escape(npc_name(t.npc) .. " · " .. (info.role or "")) .. "]" ..
		"textarea[0.4,1;11.2,5.6;;;" .. table.concat(lines, "\n") .. "]" ..
		"field[0.4,6.9;8.6,0.8;msg;;]field_close_on_enter[msg;false]" ..
		"button[9.2,6.9;2.4,0.8;send;Say]" ..
		"button[0.4,8;3.4,0.8;give;Give held item]" ..
		"button[4.2,8;3.4,0.8;trade;Trade]" ..
		"button_exit[8,8;3.6,0.8;close;Leave]"
	core.show_formspec(name, "npcasso:talk", fs)
end

local function say(name, who, text)
	local t = talk[name]
	if t then table.insert(t.history, who .. ": " .. text) end
end

function npcasso.open_talk(player, npc_id)
	local name = player:get_player_name()
	if not talk[name] or talk[name].npc ~= npc_id then
		talk[name] = {npc = npc_id, history = {}, sent = 0, busy = false,
			thread = npcasso.world() .. ":" .. name .. ":" .. npc_id .. ":" .. os.time()}
	end
	show_talk(name)
end

local function send(player, msg)
	local name = player:get_player_name()
	local t = talk[name]
	if t.busy or msg:trim() == "" then return end
	say(name, "You", msg)
	t.busy, t.sent = true, t.sent + 1
	show_talk(name)
	npcasso.post("/talk", {world = npcasso.world(), player = name, npc_id = t.npc, message = msg:sub(1, 500),
		thread_id = t.thread, game_time = npcasso.game_time()}, function(out)
		if talk[name] ~= t then return end
		t.busy = false
		say(name, npc_name(t.npc), out and out.reply or (npc_name(t.npc) .. " seems distracted."))
		apply(name, out)
		show_talk(name)
	end)
end

local function give(player)
	local name, t = player:get_player_name(), talk[player:get_player_name()]
	local stack = player:get_wielded_item()
	if stack:is_empty() then
		say(name, "*", "You have nothing in your hand.")
		return show_talk(name)
	end
	local item = stack:get_name()
	stack:take_item(1)
	player:set_wielded_item(stack)
	local desc = (core.registered_items[item] or {}).description or item
	say(name, "*", "You give " .. npc_name(t.npc) .. " " .. desc)
	npcasso.event(player, "gift", t.npc, {item = item}, {})
	show_talk(name)
end

local function trade(player)
	local name, t = player:get_player_name(), talk[player:get_player_name()]
	local e = find_npc(t.npc, player:get_pos(), 12)
	local info = npcasso.npcs[t.npc] or {}
	local has_block = true
	if info.work_block and e then
		has_block = core.find_node_near(e.object:get_pos(), WORK_RANGE, ANVILS, true) ~= nil
	end
	npcasso.post("/trade", {world = npcasso.world(), player = name, npc_id = t.npc,
		work_block_present = has_block}, function(q)
		if talk[name] ~= t then return end
		if not q then
			say(name, npc_name(t.npc), npc_name(t.npc) .. " seems distracted.")
		elseif not q.ok then
			say(name, npc_name(t.npc), q.reason == "no_work_block" and "Can't work without my anvil." or "Not today.")
		else
			local inv = player:get_inventory()
			local cost = ItemStack(q.cost.item .. " " .. q.cost.count)
			if not inv:contains_item("main", cost) then
				say(name, npc_name(t.npc), ("That'll be %d %s."):format(q.cost.count,
					(core.registered_items[q.cost.item] or {}).description or q.cost.item))
			else
				inv:remove_item("main", cost)
				local left = inv:add_item("main", ItemStack(q.give.item .. " " .. q.give.count))
				if not left:is_empty() then core.add_item(player:get_pos(), left) end
				say(name, "*", "Trade done.")
				npcasso.event(player, "trade", t.npc, {give = q.give, cost = q.cost}, {})
			end
		end
		show_talk(name)
	end)
end

core.register_on_player_receive_fields(function(player, formname, fields)
	if formname ~= "npcasso:talk" then return end
	local name = player:get_player_name()
	local t = talk[name]
	if not t then return true end
	if fields.send or fields.key_enter_field == "msg" then
		send(player, fields.msg or "")
	elseif fields.give then
		give(player)
	elseif fields.trade then
		trade(player)
	elseif fields.quit or fields.close then
		if t.sent <= 1 then npcasso.event(player, "walk_away", t.npc, {messages = t.sent}, {}) end
		talk[name] = nil
	end
	return true
end)

core.register_on_leaveplayer(function(player) talk[player:get_player_name()] = nil end)

-- World actions ------------------------------------------------------------------------------------

core.register_node("npcasso:apple_crate", {
	description = "Elise's Apple Crate",
	tiles = {"default_wood.png^default_apple.png", "default_wood.png", "default_wood.png"},
	groups = {choppy = 2, oddly_breakable_by_hand = 2},
	on_rightclick = function(pos, node, clicker)
		if not clicker or not clicker:is_player() then return end
		local left = clicker:get_inventory():add_item("main", ItemStack("default:apple"))
		if not left:is_empty() then return end
		npcasso.event(clicker, "theft", "elise", {item = "default:apple"}, npcasso.witnesses(clicker:get_pos()))
	end,
})

if not core.get_modpath("cottages") then
	core.register_node("npcasso:anvil", {
		description = "Anvil", tiles = {"default_steel_block.png"}, drawtype = "nodebox", paramtype = "light",
		node_box = {type = "fixed", fixed = {{-0.4, -0.5, -0.25, 0.4, -0.2, 0.25}, {-0.15, -0.2, -0.1, 0.15, 0.1, 0.1},
			{-0.5, 0.1, -0.2, 0.5, 0.4, 0.2}}},
		groups = {cracky = 2},
	})
end

local function is_anvil(name) return name == "cottages:anvil" or name == "npcasso:anvil" end

local function work_owner(pos)
	for _, e in ipairs(each_npc(pos, WORK_RANGE)) do
		if (npcasso.npcs[e.npc_id] or {}).work_block then return e.npc_id end
	end
end

core.register_on_dignode(function(pos, oldnode, digger)
	if not (digger and digger:is_player() and is_anvil(oldnode.name)) then return end
	local owner = work_owner(pos)
	if owner then npcasso.event(digger, "vandalism", owner, {node = oldnode.name}, npcasso.witnesses(digger:get_pos())) end
end)

core.register_on_placenode(function(pos, newnode, placer)
	if not (placer and placer:is_player() and is_anvil(newnode.name)) then return end
	local owner = work_owner(pos)
	if owner then npcasso.event(placer, "repair", owner, {node = newnode.name}, {owner}) end
end)

-- Periodic tick: promise deadlines and gossip -------------------------------------------------------

local tick_t = 0
core.register_globalstep(function(dtime)
	tick_t = tick_t + dtime
	if tick_t < TICK_SECONDS then return end
	tick_t = 0
	for _, p in ipairs(core.get_connected_players()) do
		local name = p:get_player_name()
		npcasso.post("/tick", {world = npcasso.world(), player = name, game_time = npcasso.game_time()},
			function(out) apply(name, out) end)
	end
end)

-- Spawn safety: never start stuck in terrain, water or trees -----------------------------------------

local function open(pos)
	local def = core.registered_nodes[core.get_node(pos).name]
	return def and not def.walkable and (def.liquidtype or "none") == "none"
end

local function solid(pos)
	local def = core.registered_nodes[core.get_node(pos).name]
	return def and def.walkable
end

-- Lifts the player to the first spot above them with ground underfoot and two free nodes of headroom.
local function unstick(player)
	local pos = vector.round(player:get_pos())
	if solid(vector.offset(pos, 0, -1, 0)) and open(pos) and open(vector.offset(pos, 0, 1, 0)) then return false end
	for y = 0, 80 do
		local p = vector.offset(pos, 0, y, 0)
		if solid(vector.offset(p, 0, -1, 0)) and open(p) and open(vector.offset(p, 0, 1, 0)) then
			player:set_pos(p)
			return true
		end
	end
	return false
end

core.register_on_joinplayer(function(player)
	local name = player:get_player_name()
	-- Free movement for building the village and getting around (singleplayer owner only).
	if core.is_singleplayer() or core.check_player_privs(name, {server = true}) then
		local privs = core.get_player_privs(name)
		privs.fly, privs.fast, privs.noclip = true, true, true
		core.set_player_privs(name, privs)
	end
	core.after(2, function()
		local p = core.get_player_by_name(name)
		if not p then return end
		if unstick(p) then core.chat_send_player(name, "[npcasso] Moved you out of the terrain.") end
		if not npcasso.village() then npcasso.build_village(p) end
	end)
end)

-- Starter village: built once per world where the player first stands --------------------------------

local store = core.get_mod_storage()

function npcasso.village()
	local s = store:get_string("village")
	return s ~= "" and core.deserialize(s) or nil
end

local function spawn_pos(o) return vector.offset(o, 0, 0.5, -6) end

local function pick(...)
	for _, n in ipairs({...}) do
		if core.registered_nodes[n] then return n end
	end
	return "air"
end

-- Village layout around origin o (o = first air node above ground, plaza centre):
--   Elise's stall west (faces east), Rowan's forge east (faces west), Mira's inn north (door faces south),
--   farm south-west, gravel cross paths, lamps, flowers. NPCs stand at their posts facing the plaza.
local function layout(o)
	local nodes = {}
	local function put(x, y, z, name, param2)
		nodes[#nodes + 1] = {pos = vector.offset(o, x, y, z), node = {name = name, param2 = param2 or 0}}
	end
	local function box(x1, y1, z1, x2, y2, z2, name)
		for x = x1, x2 do for y = y1, y2 do for z = z1, z2 do put(x, y, z, name) end end end
	end
	local grass, dirt = pick("default:dirt_with_grass"), pick("default:dirt")
	local wood, tree, cobble = pick("default:wood"), pick("default:tree"), pick("default:cobble")
	local fence, glass, torch = pick("default:fence_wood", "default:wood"), pick("default:glass"), pick("default:torch")
	local slab_wood, lamp = pick("stairs:slab_wood", "default:wood"), pick("default:meselamp", "default:torch")
	local flowers = {pick("flowers:rose"), pick("flowers:tulip"), pick("flowers:dandelion_yellow"), pick("flowers:viola")}

	-- Flatten a 37x37 area: clear above, grass on top, dirt below.
	box(-18, 0, -18, 18, 14, 18, "air")
	box(-18, -4, -18, 18, -2, 18, dirt)
	box(-18, -1, -18, 18, -1, 18, grass)
	-- Paths
	box(-1, -1, -16, 1, -1, 16, pick("default:gravel"))
	box(-16, -1, -1, 16, -1, 1, pick("default:gravel"))

	-- Elise's fruit stall (west)
	for _, c in ipairs({{-9, -2}, {-9, 2}, {-6, -2}, {-6, 2}}) do box(c[1], 0, c[2], c[1], 2, c[2], tree) end
	box(-9, 3, -2, -6, 3, 2, slab_wood)
	box(-6, 0, -1, -6, 0, 1, fence)
	put(-5, 0, -1, "npcasso:apple_crate")   -- in front: Elise sees you take it
	put(-11, 0, 0, "npcasso:apple_crate")   -- behind her back: she doesn't

	-- Rowan's forge (east)
	box(10, 0, -3, 10, 3, 3, cobble)
	box(6, 0, -3, 10, 3, -3, cobble)
	box(6, 0, 3, 10, 3, 3, cobble)
	box(6, 4, -3, 10, 4, 3, cobble)
	put(9, 0, -2, pick("default:furnace"))
	put(8, 0, 1, pick("cottages:anvil", "npcasso:anvil"))
	put(9, 0, 2, torch, 1)

	-- Mira's inn (north)
	box(-4, -1, 8, 4, -1, 14, wood)
	box(-4, 0, 8, 4, 3, 8, wood)
	box(-4, 0, 14, 4, 3, 14, wood)
	box(-4, 0, 8, -4, 3, 14, wood)
	box(4, 0, 8, 4, 3, 14, wood)
	box(-4, 4, 8, 4, 4, 14, slab_wood)
	box(0, 0, 8, 0, 1, 8, "air")                         -- door
	for _, z in ipairs({10, 12}) do put(-4, 1, z, glass); put(4, 1, z, glass) end
	put(-2, 1, 8, glass); put(2, 1, 8, glass)
	local bed_b, bed_t = pick("beds:bed_bottom"), pick("beds:bed_top")
	if bed_b ~= "air" then
		for _, x in ipairs({-3, 3}) do put(x, 0, 12, bed_b, 0); put(x, 0, 13, bed_t, 0) end
	end
	put(0, 3, 11, lamp)
	put(-1, 0, 7, torch, 1); put(1, 0, 7, torch, 1)

	-- Farm (south-west) with a water source in the middle
	box(-14, -1, -14, -8, -1, -8, pick("farming:soil_wet", "default:dirt"))
	box(-14, 0, -14, -8, 0, -8, pick("farming:wheat_8", "air"))
	put(-11, -1, -11, pick("default:water_source")); put(-11, 0, -11, "air")

	-- Lamp posts on the plaza corners
	for _, c in ipairs({{3, 3}, {-3, 3}, {3, -3}, {-3, -3}}) do
		box(c[1], 0, c[2], c[1], 1, c[2], fence)
		put(c[1], 2, c[2], lamp)
	end
	-- Flowers along the edges (deterministic, so every world looks the same)
	for i = -16, 16, 3 do
		for _, z in ipairs({-17, 17}) do put(i, 0, z, flowers[(i % 4) + 1]) end
		for _, x in ipairs({-17, 17}) do put(x, 0, i, flowers[((i + 1) % 4) + 1]) end
	end
	return nodes
end

-- Where each NPC stands and which way they face (yaw: 0 = +z, pi/2 = -x, -pi/2 = +x, pi = -z).
local POSTS = {
	elise = {x = -8, z = 0, yaw = -math.pi / 2},
	rowan = {x = 7, z = 0, yaw = math.pi / 2},
	mira = {x = 0, z = 6, yaw = math.pi},
}

function npcasso.build_village(player)
	local o = vector.round(player:get_pos())
	local name = player:get_player_name()
	core.chat_send_player(name, "[npcasso] Building the village...")
	core.emerge_area(vector.offset(o, -20, -6, -20), vector.offset(o, 20, 16, 20), function(_, _, remaining)
		if remaining > 0 then return end
		for _, n in ipairs(layout(o)) do core.set_node(n.pos, n.node) end
		for id, post in pairs(POSTS) do
			core.add_entity(vector.offset(o, post.x, 0.5, post.z), "npcasso:npc",
				core.serialize({npc_id = id, yaw = post.yaw}))
		end
		store:set_string("village", core.serialize(o))
		local p = core.get_player_by_name(name)
		if p then
			p:set_pos(spawn_pos(o))
			p:set_look_horizontal(0)
		end
		core.chat_send_player(name, "[npcasso] Welcome to the village. /npcasso home brings you back here.")
	end)
end

core.register_on_respawnplayer(function(player)
	local o = npcasso.village()
	if not o then return false end
	player:set_pos(spawn_pos(o))
	return true
end)

-- Commands -----------------------------------------------------------------------------------------

local function load_npcs(cb)
	npcasso.get("/npcs", function(n)
		if n then
			npcasso.npcs = n
			for _, e in pairs(core.luaentities) do
				if e.name == "npcasso:npc" then set_look(e) end
			end
		end
		if cb then cb(n) end
	end)
end

-- Keep trying until the backend answers, so NPCs get names and skins even if it starts after the game.
local function load_until_ready()
	load_npcs(function(n) if not n then core.after(10, load_until_ready) end end)
end
core.after(1, load_until_ready)

core.register_chatcommand("npcasso", {
	params = "home | village | spawn <npc_id> | remove | debug | reload | unstuck",
	description = "NPCasso tools",
	privs = {server = true},
	func = function(name, param)
		local player = core.get_player_by_name(name)
		local cmd, arg = param:match("^(%S*)%s*(%S*)")
		if cmd == "home" then
			local o = npcasso.village()
			if not o then return false, "No village yet." end
			player:set_pos(spawn_pos(o))
			return true, "Welcome back."
		elseif cmd == "village" then
			store:set_string("village", "")
			npcasso.build_village(player)
			return true
		elseif cmd == "unstuck" then
			return true, unstick(player) and "Moved you to open ground." or "You're already standing free (or no ground above)."
		elseif cmd == "spawn" then
			if not npcasso.npcs[arg] then return false, "Unknown NPC. Known: " .. table.concat((function()
				local k = {} for id in pairs(npcasso.npcs) do table.insert(k, id) end return k end)(), ", ") end
			core.add_entity(player:get_pos(), "npcasso:npc",
				core.serialize({npc_id = arg, yaw = player:get_look_horizontal()}))
			return true, "Spawned " .. arg .. " facing where you look."
		elseif cmd == "remove" then
			local e = each_npc(player:get_pos(), 3)[1]
			if not e then return false, "No NPC within 3 nodes." end
			e.object:remove()
			return true, "Removed " .. e.npc_id
		elseif cmd == "reload" then
			load_npcs(function(n)
				core.chat_send_player(name, n and "NPC list reloaded." or "Backend unreachable.")
			end)
			return true
		elseif cmd == "debug" then
			local ids, out = {}, {}
			for id in pairs(npcasso.npcs) do table.insert(ids, id) end
			local function step(i)
				if i > #ids then
					return core.show_formspec(name, "npcasso:debug", "formspec_version[6]size[14,11]" ..
						"textarea[0.4,0.4;13.2,10.2;;NPCasso debug (hidden from players);" ..
						core.formspec_escape(table.concat(out, "\n")) .. "]")
				end
				npcasso.get(("/npc/%s?world=%s&player=%s"):format(ids[i], npcasso.world(), name), function(s)
					if s then
						table.insert(out, ("%s  trust %d (%s)"):format(s.npc.name, s.trust, s.band))
						for _, m in ipairs(s.memories) do
							table.insert(out, ("   - [%s] %s (%s)"):format(m.type, m.text, m.how))
						end
						for _, p in ipairs(s.open_promises) do
							table.insert(out, ("   * %s: %d %s by day %.1f"):format(p.kind, p.count, p.item, p.deadline))
						end
					else
						table.insert(out, ids[i] .. ": backend unreachable")
					end
					step(i + 1)
				end)
			end
			step(1)
			return true
		end
		return false, "Usage: /npcasso " .. "home | village | spawn <npc_id> | remove | debug | reload | unstuck"
	end,
})
