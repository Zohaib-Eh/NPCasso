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

local store = core.get_mod_storage()

-- World id = save folder name + a random id kept in this save's mod storage. Deleting the save deletes the id,
-- so a new world with the same name starts with NPCs who remember nothing. Copied saves keep the id but get a
-- different folder name, so demo copies don't share memories either.
if store:get_string("world_id") == "" then
	math.randomseed(os.time() + core.get_us_time())
	store:set_string("world_id", ("%08x"):format(math.random(0, 0x7fffffff)))
end
local WORLD_ID = core.get_worldpath():match("([^/\\]+)$") .. "-" .. store:get_string("world_id")
function npcasso.world() return WORLD_ID end
function npcasso.game_time() return core.get_day_count() + core.get_timeofday() end

local function npc_name(id) return (npcasso.npcs[id] or {}).name or id end

-- Notices and responses ----------------------------------------------------------------------------

local notice_queue = {}  -- player name -> {showing = bool, list = {...}}

local function next_notice(player)
	local name = player:get_player_name()
	local q = notice_queue[name]
	if not q or #q.list == 0 then
		if q then q.showing = false end
		return
	end
	q.showing = true
	local id = player:hud_add({type = "text", position = {x = 0.5, y = 0.18}, alignment = {x = 0, y = 0},
		text = table.remove(q.list, 1), number = 0xFFE7A8, scale = {x = 100, y = 100}, size = {x = 2}})
	core.after(2.5, function()
		if not player:is_player() then return end
		player:hud_remove(id)
		next_notice(player)
	end)
end

function npcasso.notice(player, text)
	local name = player:get_player_name()
	notice_queue[name] = notice_queue[name] or {showing = false, list = {}}
	local q = notice_queue[name]
	for _, t in ipairs(q.list) do if t == text then return end end  -- already queued
	table.insert(q.list, text)
	if not q.showing then next_notice(player) end
end

-- "Elise will remember that." + "Mira will remember that." -> "Elise and Mira will remember that."
local function merge_remembers(notices)
	local names, rest = {}, {}
	for _, n in ipairs(notices or {}) do
		local who = n:match("^(.-) will remember that%.$")
		if who then table.insert(names, who) else table.insert(rest, n) end
	end
	if #names > 0 then
		local who = #names == 1 and names[1] or table.concat(names, ", ", 1, #names - 1) .. " and " .. names[#names]
		table.insert(rest, 1, who .. " will remember that.")
	end
	return rest
end

-- Shows notices/shouts and hands out items from any backend response.
local function apply(name, out)
	local player = core.get_player_by_name(name)
	if not player or not out then return end
	for _, s in ipairs(out.shouts or {}) do
		npcasso.bubble(s.npc_id, s.text)
		npcasso.feed(player, npc_name(s.npc_id) .. ": " .. s.text, 0xFFD27F)
		core.chat_send_player(name, core.colorize("#FFD27F", "<" .. npc_name(s.npc_id) .. "> ") .. s.text)
	end
	for _, n in ipairs(merge_remembers(out.notices)) do
		npcasso.feed(player, n, n:find("remember") and 0xFF9E7A or 0xFFE7A8)
		if n:find("remember") then npcasso.notice(player, n) end  -- the signature moment stays centre-screen
	end
	if (out.xp_gained or 0) > 0 then
		npcasso.feed(player, "+" .. out.xp_gained .. " XP", 0x9AE07A)
		npcasso.refresh_player(name)
	end
	if out.level_up then npcasso.level_up(player, out.level_up) end
	if out.event_id then npcasso.refresh_moods() end
	for _, g in ipairs(out.give or {}) do
		local left = player:get_inventory():add_item("main", ItemStack(g.item .. " " .. g.count))
		if not left:is_empty() then core.add_item(player:get_pos(), left) end
	end
end

npcasso.apply = apply

local function npc_entity(id)
	for _, e in pairs(core.luaentities) do
		if e.name == "npcasso:npc" and e.npc_id == id then return e end
	end
end

function npcasso.event(player, type, target, details, witnesses)
	local name = player:get_player_name()
	-- Instant feedback: witnesses stop, turn to the player and show "!" while the backend thinks.
	for _, id in ipairs(witnesses or {}) do
		local e = npc_entity(id)
		if e then
			local d = vector.subtract(player:get_pos(), e.object:get_pos())
			e.path, e.rest, e.meet_until = nil, 5, os.time() + 4
			e.object:set_velocity({x = 0, y = 0, z = 0})
			e.object:set_yaw(math.atan2(-d.x, d.z))
			npcasso.bubble(id, "!", 4)
			if (type == "theft" or type == "vandalism" or type == "hit_npc") and id ~= "wren" then
				e.errand = "wren"  -- off to tell the guard
			end
		end
	end
	npcasso.post("/event", {world = npcasso.world(), player = name, type = type, target = target,
		details = details or {}, witnesses = witnesses or {}, game_time = npcasso.game_time()},
		function(out)
			apply(name, out)  -- notices and items now; the spoken reaction follows
			if out and out.react and #out.react > 0 then
				npcasso.post("/react", {world = npcasso.world(), player = name, event_id = out.event_id,
					npc_ids = out.react}, function(r) apply(name, r) end)
			end
		end)
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
			table.insert(seen, {id = e.npc_id, d = vector.distance(pos, npos)})
		end
	end
	table.sort(seen, function(a, b) return a.d < b.d end)
	local ids = {}
	for _, s in ipairs(seen) do table.insert(ids, s.id) end
	return ids
end

local function set_look(self)
	local info = npcasso.npcs[self.npc_id] or {}
	self.object:set_properties({
		nametag = (info.name or tostring(self.npc_id)) .. " · " .. (info.role or ""),
		nametag_color = "#FFFFFF", nametag_bgcolor = "#00000060",
		textures = {info.skin or "character.png"},
	})
end

npcasso.each_npc, npcasso.find_npc, npcasso.npc_entity, npcasso.npc_name = each_npc, find_npc, npc_entity, npc_name
npcasso.talk = talk

local ANIM_STAND, ANIM_WALK = {x = 0, y = 79}, {x = 168, y = 187}
npcasso.ANIM_STAND, npcasso.ANIM_WALK = ANIM_STAND, ANIM_WALK
local WANDER, WALK_SPEED, GREET_RANGE, GREET_COOLDOWN = 3, 1.2, 5, 180

local function stop(self)
	local v = self.object:get_velocity()
	self.object:set_velocity({x = 0, y = v.y, z = 0})
	if self.target then self.object:set_animation(ANIM_STAND, 30, 0) end
	self.target = nil
end

-- Speech bubble: the NPC's nametag shows what they say for a few seconds, then goes back to name and role.
local bubble_token = {}
local function wrap(text, width, max_lines)
	local lines, line = {}, ""
	for word in tostring(text):gmatch("%S+") do
		if #line + #word + 1 > width and line ~= "" then
			table.insert(lines, line)
			line = word
		else
			line = line == "" and word or line .. " " .. word
		end
	end
	if line ~= "" then table.insert(lines, line) end
	if #lines > max_lines then
		lines = {unpack(lines, 1, max_lines)}
		lines[max_lines] = lines[max_lines] .. "..."
	end
	return table.concat(lines, "\n")
end

function npcasso.bubble(npc_id, text, secs)
	local token = {}
	bubble_token[npc_id] = token
	for _, e in pairs(core.luaentities) do
		if e.name == "npcasso:npc" and e.npc_id == npc_id then
			e.object:set_properties({nametag = wrap(text, 34, 4) .. "\n\n" .. npc_name(npc_id),
				nametag_color = "#FFF3DC", nametag_bgcolor = "#000000B0"})
		end
	end
	core.after(secs or 7, function()
		if bubble_token[npc_id] ~= token then return end
		for _, e in pairs(core.luaentities) do
			if e.name == "npcasso:npc" and e.npc_id == npc_id then set_look(e) end
		end
	end)
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
		self.greeted, self.rest = {}, math.random(2, 8)
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
			local mood = npcasso.moods[self.npc_id]
			if mood ~= "afraid" and mood ~= "hostile" and (self.meet_until or 0) <= os.time()
				and vector.distance(p:get_pos(), pos) < GREET_RANGE and os.time() - (self.greeted[name] or 0) > GREET_COOLDOWN then
				self.greeted[name] = os.time()
				stop(self)
				local d = vector.subtract(p:get_pos(), pos)
				self.object:set_yaw(math.atan2(-d.x, d.z))
				self.rest = 6
				npcasso.post("/greet", {world = npcasso.world(), player = name, npc_id = self.npc_id,
					thread_id = npcasso.world() .. ":" .. name .. ":" .. self.npc_id .. ":greet:" .. os.time(),
					game_time = npcasso.game_time()}, function(out)
					if out and out.reply ~= "" and not talk[name] then
						npcasso.bubble(self.npc_id, out.reply)
						npcasso.feed(name, npc_name(self.npc_id) .. ": " .. out.reply, 0xFFD27F)
						core.chat_send_player(name, core.colorize("#FFD27F", "<" .. npc_name(self.npc_id) .. "> ") .. out.reply)
					end
				end)
			end
		end

		npcasso.life_step(self, dt, pos)  -- roaming, motives, meetings (life.lua)
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

local function plain(s) return (tostring(s):gsub("[<>]", "")) end

local function show_talk(name)
	local t = talk[name]
	if not t then return end
	local info = npcasso.npcs[t.npc] or {}
	local log = {}
	for i = math.max(1, #t.history - 11), #t.history do
		local h = t.history[i]
		if h.who == "*" then
			table.insert(log, "<i><style color=#A0A0A0>" .. plain(h.text) .. "</style></i>")
		else
			local color = h.who == "You" and "#9AD0FF" or "#FFD27F"
			table.insert(log, "<b><style color=" .. color .. ">" .. plain(h.who) .. "</style></b>  " .. plain(h.text))
		end
	end
	if t.busy then
		table.insert(log, "<i><style color=#A0A0A0>" .. plain(npc_name(t.npc)) .. " is thinking...</style></i>")
	end
	local fs = "formspec_version[6]size[15,10.6]" ..
		"style_type[button,button_exit;bgcolor=#7a5a33;textcolor=#FFF3DC]" ..
		"box[0.3,0.3;4.3,7.7;#00000044]" ..
		"model[0.4,0.4;4.1,7.5;portrait;character.b3d;" .. core.formspec_escape(info.skin or "character.png") ..
		";-5,200;false;true;0,79;30]" ..
		"hypertext[0.3,8.15;4.3,1.4;title;" .. core.formspec_escape("<global halign=center><big><b>" ..
		plain(info.name or t.npc) .. "</b></big>\n<style color=#BBBBBB>" .. plain(info.role or "") .. "</style>") .. "]" ..
		"box[4.9,0.3;9.8,7.7;#00000066]" ..
		"hypertext[5.1,0.45;9.5,7.4;log;" .. core.formspec_escape("<global valign=bottom color=#EEEEEE size=16>" ..
		table.concat(log, "\n\n")) .. "]" ..
		"field[4.9,8.25;7.5,0.9;msg;;]field_close_on_enter[msg;false]" ..
		"button[12.6,8.25;2.1,0.9;send;Say]" ..
		"button[4.9,9.4;2.3,0.9;trade;Trade]" ..
		"button[7.4,9.4;2.3,0.9;quests;Quests]" ..
		"button[9.9,9.4;2.5,0.9;give;Give held item]" ..
		"button_exit[12.6,9.4;2.1,0.9;close;Leave]" ..
		"set_focus[msg;true]"
	core.show_formspec(name, "npcasso:talk", fs)
end

local function say(name, who, text)
	local t = talk[name]
	if t then table.insert(t.history, {who = who, text = text}) end
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
	npcasso.post("/talk", {world = npcasso.world(), player = name, npc_id = t.npc, message = msg,
		thread_id = t.thread, game_time = npcasso.game_time()}, function(out)
		if talk[name] ~= t then return end
		t.busy = false
		say(name, npc_name(t.npc), out and out.reply or (npc_name(t.npc) .. " seems distracted."))
		apply(name, out)
		if not t.trading then show_talk(name) end
	end)
end

local function give(player)
	local name, t = player:get_player_name(), talk[player:get_player_name()]
	local stack = player:get_wielded_item()
	if stack:is_empty() then
		say(name, "*", "You have nothing in your hand.")
		return show_talk(name)
	end
	local item, desc = stack:get_name(), stack:get_short_description()
	stack:take_item(1)
	player:set_wielded_item(stack)
	say(name, "*", "You give " .. npc_name(t.npc) .. " " .. desc .. ".")
	npcasso.event(player, "gift", t.npc, {item = item}, {})
	show_talk(name)
end

-- Trade window: one offer per NPC, Minecraft villager style. The price comes from the backend (hidden trust).
local function short(item) return ItemStack(item):get_short_description() end

local function show_trade(name)
	local t = talk[name]
	if not t then return end
	local q, info = t.quote, npcasso.npcs[t.npc] or {}
	local fs = "formspec_version[6]size[10.5,10.2]" ..
		"style_type[button,button_exit;bgcolor=#7a5a33;textcolor=#FFF3DC]" ..
		"hypertext[0.4,0.3;9.7,0.8;title;" .. core.formspec_escape("<big><b>Trade with " ..
		plain(info.name or t.npc) .. "</b></big>") .. "]" ..
		"box[0.4,1.2;9.7,2.1;#00000055]"
	if q == nil then
		fs = fs .. "label[0.8,2.2;" .. core.formspec_escape(npc_name(t.npc) .. " is thinking about a price...") .. "]"
	elseif q.ok then
		fs = fs ..
			"item_image_button[0.9,1.5;1.5,1.5;" .. q.cost.item .. ";cost;" .. q.cost.count .. "]" ..
			"image[2.8,1.8;1.6,0.9;gui_furnace_arrow_bg.png^[transformR270]" ..
			"item_image_button[4.8,1.5;1.5,1.5;" .. q.give.item .. ";give_item;" .. q.give.count .. "]" ..
			"button[7.1,1.75;2.7,1.0;do_trade;Trade]" ..
			"tooltip[cost;" .. core.formspec_escape(q.cost.count .. " x " .. short(q.cost.item)) .. "]" ..
			"tooltip[give_item;" .. core.formspec_escape(q.give.count .. " x " .. short(q.give.item)) .. "]"
	else
		fs = fs .. "label[0.8,2.2;" .. core.formspec_escape(q.reason == "no_work_block" and
			"\"I can't work without my anvil.\"" or "\"Not today. Not for you.\"") .. "]"
	end
	fs = fs .. "label[0.4,3.75;" .. core.formspec_escape(t.trade_status or "") .. "]" ..
		"list[current_player;main;0.4,4.3;8,1;]" ..
		"list[current_player;main;0.4,5.65;8,3;8]" ..
		"button[0.4,9.2;3,0.8;back;Back]" ..
		"button_exit[7.1,9.2;3,0.8;close;Leave]"
	core.show_formspec(name, "npcasso:trade", fs)
end

local function work_block_present(player, npc_id)
	if not (npcasso.npcs[npc_id] or {}).work_block then return true end
	local e = find_npc(npc_id, player:get_pos(), 16)
	return e ~= nil and core.find_node_near(e.object:get_pos(), WORK_RANGE, ANVILS, true) ~= nil
end

local function quote(player, cb)
	local name, t = player:get_player_name(), talk[player:get_player_name()]
	npcasso.post("/trade", {world = npcasso.world(), player = name, npc_id = t.npc,
		work_block_present = work_block_present(player, t.npc)}, function(q)
		if talk[name] ~= t then return end
		t.quote = q or {ok = false, reason = "distracted"}
		cb(t)
	end)
end

local function open_trade(player)
	local name, t = player:get_player_name(), talk[player:get_player_name()]
	t.trading, t.quote, t.trade_status = true, nil, ""
	show_trade(name)
	quote(player, function() show_trade(name) end)
end

local function do_trade(player)
	local name = player:get_player_name()
	quote(player, function(t)  -- re-quote: trust may have changed since the window opened
		local q = t.quote
		if q.ok then
			local inv = player:get_inventory()
			local cost = ItemStack(q.cost.item .. " " .. q.cost.count)
			if not inv:contains_item("main", cost) then
				t.trade_status = "You need " .. q.cost.count .. " x " .. short(q.cost.item) .. "."
			else
				inv:remove_item("main", cost)
				local left = inv:add_item("main", ItemStack(q.give.item .. " " .. q.give.count))
				if not left:is_empty() then core.add_item(player:get_pos(), left) end
				t.trade_status = "Traded for " .. q.give.count .. " x " .. short(q.give.item) .. "."
				say(name, "*", t.trade_status)
				npcasso.event(player, "trade", t.npc, {give = q.give, cost = q.cost}, {})
			end
		end
		show_trade(name)
	end)
end

core.register_on_player_receive_fields(function(player, formname, fields)
	if formname ~= "npcasso:talk" and formname ~= "npcasso:trade" then return end
	local name = player:get_player_name()
	local t = talk[name]
	if not t then return true end
	if fields.send or fields.key_enter_field == "msg" then
		send(player, fields.msg or "")
	elseif fields.give then
		give(player)
	elseif fields.trade then
		open_trade(player)
	elseif fields.do_trade then
		do_trade(player)
	elseif fields.quests then
		npcasso.show_npc_quests(player, t.npc)
	elseif fields.back then
		t.trading = false
		show_talk(name)
	elseif fields.quit or fields.close then
		if t.sent <= 1 and formname == "npcasso:talk" then
			npcasso.event(player, "walk_away", t.npc, {messages = t.sent}, {})
		end
		npcasso.on_talk_closed(name, t.npc)
		talk[name] = nil
	end
	return true
end)

core.register_on_leaveplayer(function(player) talk[player:get_player_name()] = nil end)

-- World actions ------------------------------------------------------------------------------------

local RETURNABLE = {["default:apple"] = true, ["farming:bread"] = true}

-- Elise's stock chest: opens like a Minecraft chest. Taking anything out is theft; she may or may not see it.
local CRATE_FS = "size[8,8.5]label[0,0;Elise's stock (not yours - put things back to make amends)]list[context;main;0,0.5;8,2;]" ..
	"list[current_player;main;0,3.85;8,1;]list[current_player;main;0,5.08;8,3;8]" ..
	"listring[context;main]listring[current_player;main]"

local function stock_crate(pos)
	local meta = core.get_meta(pos)
	meta:set_string("formspec", CRATE_FS)
	meta:set_string("infotext", "Elise's stock")
	local inv = meta:get_inventory()
	inv:set_size("main", 16)
	if inv:is_empty("main") then
		for i = 1, 6 do inv:set_stack("main", i, "default:apple 10") end
		if core.registered_items["farming:bread"] then inv:set_stack("main", 7, "farming:bread 5") end
	end
end

core.register_node("npcasso:apple_crate", {
	description = "Elise's Stock Chest",
	tiles = {"default_chest_top.png", "default_chest_top.png", "default_chest_side.png",
		"default_chest_side.png", "default_chest_side.png", "default_chest_front.png"},
	paramtype2 = "facedir",
	groups = {choppy = 2, oddly_breakable_by_hand = 2},
	on_construct = stock_crate,
	allow_metadata_inventory_put = function(pos, listname, index, stack)
		return RETURNABLE[stack:get_name()] and stack:get_count() or 0
	end,
	on_metadata_inventory_put = function(pos, listname, index, stack, player)
		if not player or not player:is_player() then return end
		npcasso.event(player, "return", "elise", {item = stack:get_name(), count = stack:get_count()}, {})
	end,
	allow_metadata_inventory_move = function() return 0 end,
	on_metadata_inventory_take = function(pos, listname, index, stack, player)
		if not player or not player:is_player() then return end
		npcasso.event(player, "theft", "elise", {item = stack:get_name(), count = stack:get_count()},
			npcasso.witnesses(player:get_pos()))
	end,
})

-- Crates placed before this version had no inventory; stock them when loaded.
core.register_lbm({
	name = "npcasso:stock_old_crates", nodenames = {"npcasso:apple_crate"}, run_at_every_load = true,
	action = function(pos)
		if core.get_meta(pos):get_string("formspec") == "" then stock_crate(pos) end
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
		if not npcasso.village() then npcasso.build_village(p) else npcasso.give_starter_kit(p) end
	end)
end)

-- Village Guide: the in-game tutorial -------------------------------------------------------------

local GUIDE = {
	{"Start", "<big><b>Welcome to the village</b></big>\n\n" ..
		"The villagers here are not background characters. They <b>remember</b> what you do to them, " ..
		"they judge you for it, and they <b>talk to each other</b>.\n\n" ..
		"<b>Move</b> W A S D   <b>Jump</b> Space   <b>Inventory</b> I\n" ..
		"<b>Fly</b> K, then Space / Shift   <b>Fast</b> J   <b>Lost?</b> /npcasso home\n\n" ..
		"<b>Talk</b>: right-click a villager and type anything. Ask them how things work - they know."},
	{"Farming", "<big><b>Growing wheat and baking bread</b></big>\n\n" ..
		"1. Hold the <b>hoe</b> (in your starter kit) and left-click dirt or grass <b>near water</b> to till it.\n" ..
		"2. Right-click the tilled soil with <b>wheat seeds</b> to plant. Cut tall grass to find more seeds.\n" ..
		"3. Wait until the wheat turns <b>golden</b>, then break it to harvest wheat (and seeds).\n" ..
		"4. Put wheat in the crafting grid (I) to make <b>flour</b>.\n" ..
		"5. Bake flour in a <b>furnace</b> to get <b>bread</b>.\n\n" ..
		"There is a ready farm south-west of the square with water in the middle."},
	{"Trading", "<big><b>Trading</b></big>\n\n" ..
		"Talk to a villager and press <b>Trade</b>.\n" ..
		"Elise: apples for iron ingots.  Rowan: steel pickaxes for iron.  Mira: bread for apples.\n\n" ..
		"<b>Prices depend on how they feel about you.</b> You will never see a number - you will see it in " ..
		"their prices, their tone, and whether they serve you at all.\n\n" ..
		"Iron: mine iron ore with a pickaxe and smelt it in a furnace with coal."},
	{"Villagers", "<big><b>Living with people who remember</b></big>\n\n" ..
		"<b>Elise</b> (fruit stall, west) - honest, careful. Taking from her chest is theft if she sees you.\n" ..
		"<b>Rowan</b> (forge, east) - blunt and proud. Don't touch his anvil.\n" ..
		"<b>Mira</b> (inn, north) - hears everything. Rumours start with her.\n\n" ..
		"<b>Making amends</b>: apologise, put stolen things back in Elise's chest, keep your promises, " ..
		"bring gifts they love (ask them what they like).\n\n" ..
		"When you see <b>\"... will remember that.\"</b>, it stuck."},
	{"Quests", "<big><b>Quests, XP and levels</b></big>\n\n" ..
		"The <b>quest board</b> in the town hall (south-east) lists every villager's requests. Press <b>Accept</b>.\n" ..
		"Or ask a villager directly: in the talk window press <b>Quests</b>, then <b>Hand in items</b> when you have them.\n" ..
		"Villagers may also ask for things in conversation - those go straight into your <b>Journal</b>.\n\n" ..
		"<b>XP</b> comes from quests, trades, harvests, slaying monsters and keeping promises. " ..
		"Levels unlock trades (Rowan forges only for Lv 2+) and change how villagers address you.\n\n" ..
		"<b>Monsters</b> roam outside the village at night. Wren the guard will thank you for thinning them out."},
	{"Festival", "<big><b>The Harvest Festival</b></big>\n\n" ..
		"Finish every villager's <b>main quest</b> (marked *) and reach <b>Lv 4</b>, then begin the festival at the quest board.\n\n" ..
		"Every villager votes on whether you belong here. Their vote is how they truly feel about you - " ..
		"every theft, gift, promise and apology they remember, and every rumour they heard.\n\n" ..
		"<b>Hero</b>, <b>Accepted</b> or <b>Turned away</b>. You only get one festival."},
}

function npcasso.show_guide(name, tab)
	tab = tonumber(tab) or 1
	local titles = {}
	for _, g in ipairs(GUIDE) do table.insert(titles, g[1]) end
	core.show_formspec(name, "npcasso:guide", "formspec_version[6]size[13,10]" ..
		"tabheader[0,0;guide_tab;" .. table.concat(titles, ",") .. ";" .. tab .. ";false;true]" ..
		"box[0.3,0.3;12.4,8.4;#00000055]" ..
		"hypertext[0.6,0.5;11.8,8;text;" .. core.formspec_escape("<global color=#EEEEEE size=17>" .. GUIDE[tab][2]) .. "]" ..
		"style_type[button_exit;bgcolor=#7a5a33;textcolor=#FFF3DC]button_exit[4.75,8.95;3.5,0.8;close;Got it]")
end

core.register_on_player_receive_fields(function(player, formname, fields)
	if formname ~= "npcasso:guide" then return end
	if fields.guide_tab then npcasso.show_guide(player:get_player_name(), fields.guide_tab) end
	return true
end)

core.register_craftitem("npcasso:guide", {
	description = "Village Guide",
	inventory_image = "default_book.png",
	stack_max = 1,
	on_use = function(itemstack, user)
		if user and user:is_player() then npcasso.show_guide(user:get_player_name()) end
	end,
})

function npcasso.give_starter_kit(player)
	local key = "kit_" .. player:get_player_name()
	if store:get_string(key) ~= "" then return end
	store:set_string(key, "1")
	local inv = player:get_inventory()
	for _, item in ipairs({"npcasso:guide", "farming:hoe_wood", "farming:seed_wheat 10", "default:steel_ingot 6",
			"farming:bread 3", "default:torch 10"}) do
		if core.registered_items[ItemStack(item):get_name()] then inv:add_item("main", item) end
	end
end

-- Starter village: built once per world where the player first stands --------------------------------

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
npcasso.VILLAGE_RADIUS = 42
npcasso.layout_extras = {}  -- functions(put, box, pick) adding buildings (town.lua)

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

	-- Flatten a 61x61 area: clear above, grass on top, dirt below.
	local R = npcasso.VILLAGE_RADIUS
	box(-R, 0, -R, R, 14, R, "air")
	box(-R, -4, -R, R, -2, R, dirt)
	box(-R, -1, -R, R, -1, R, grass)
	-- Paths
	box(-1, -1, -R + 2, 1, -1, R - 2, pick("default:gravel"))
	box(-R + 2, -1, -1, R - 2, -1, 1, pick("default:gravel"))

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
	for _, extra in ipairs(npcasso.layout_extras) do extra(put, box, pick) end
	return nodes
end

-- Where each NPC stands and which way they face (yaw: 0 = +z, pi/2 = -x, -pi/2 = +x, pi = -z).
npcasso.posts = {
	elise = {x = -8, z = 0, yaw = -math.pi / 2},
	rowan = {x = 7, z = 0, yaw = math.pi / 2},
	mira = {x = 0, z = 6, yaw = math.pi},
}
npcasso.spawn_pos = spawn_pos

function npcasso.build_village(player, origin)
	local o = origin or vector.round(player:get_pos())
	local name = player:get_player_name()
	core.chat_send_player(name, "[npcasso] Building the village...")
	local R = npcasso.VILLAGE_RADIUS + 2
	core.emerge_area(vector.offset(o, -R, -6, -R), vector.offset(o, R, 16, R), function(_, _, remaining)
		if remaining > 0 then return end
		for _, n in ipairs(layout(o)) do core.set_node(n.pos, n.node) end
		for _, e in pairs(core.luaentities) do  -- rebuilding: replace, don't duplicate, the villagers
			if e.name == "npcasso:npc" then e.object:remove() end
		end
		for id, post in pairs(npcasso.posts) do
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
		if p then
			npcasso.give_starter_kit(p)
			core.after(1, npcasso.show_guide, name, 1)
		end
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
	params = "guide | journal | board | home | village | spawn <npc_id> | remove | debug | reload | unstuck",
	description = "NPCasso tools",
	privs = {server = true},
	func = function(name, param)
		local player = core.get_player_by_name(name)
		local cmd, arg = param:match("^(%S*)%s*(%S*)")
		if cmd == "journal" then
			npcasso.show_journal(name)
			return true
		elseif cmd == "board" then
			npcasso.show_board(name)
			return true
		elseif cmd == "guide" then
			npcasso.show_guide(name)
			return true
		elseif cmd == "home" then
			local o = npcasso.village()
			if not o then return false, "No village yet." end
			player:set_pos(spawn_pos(o))
			return true, "Welcome back."
		elseif cmd == "village" then
			local o = npcasso.village()  -- rebuild in place if there is one; otherwise build where you stand
			store:set_string("village", "")
			npcasso.build_village(player, o)
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
		return false, "Usage: /npcasso " .. "guide | journal | board | home | village | spawn <npc_id> | remove | debug | reload | unstuck"
	end,
})

local MODPATH = core.get_modpath("npcasso")
dofile(MODPATH .. "/hud.lua")
dofile(MODPATH .. "/life.lua")
dofile(MODPATH .. "/town.lua")
