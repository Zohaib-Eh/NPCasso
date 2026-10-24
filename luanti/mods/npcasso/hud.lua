-- HUD: bottom-left message feed, XP bar, level-up popup.

local FEED_LINES, FEED_SECONDS, LINE_HEIGHT = 6, 8, 22
local feeds = {}   -- player name -> list of {id, t}, newest first
local xp_hud = {}  -- player name -> hud id

local function restack(player, list)
	for i, line in ipairs(list) do
		player:hud_change(line.id, "offset", {x = 16, y = -(i - 1) * LINE_HEIGHT})
	end
end

-- Adds a line to the player's bottom-left feed. Lines fade out after FEED_SECONDS.
local function wrap_feed(text)
	local out, line = {}, ""
	for word in tostring(text):gmatch("%S+") do
		local next_line = line == "" and word or (line .. " " .. word)
		if #next_line > 42 and line ~= "" then
			table.insert(out, line)
			line = word
		else
			line = next_line
		end
	end
	if line ~= "" then table.insert(out, line) end
	return out
end

function npcasso.feed(player, text, color)
	if type(player) == "string" then player = core.get_player_by_name(player) end
	if not player or not player:is_player() then return end
	local name = player:get_player_name()
	local list = feeds[name] or {}
	feeds[name] = list
	for _, line in ipairs(wrap_feed(text)) do
		local id = player:hud_add({type = "text", position = {x = 0, y = 0.68}, alignment = {x = 1, y = -1},
			offset = {x = 16, y = 0}, text = line, number = color or 0xFFFFFF, scale = {x = 100, y = 40},
			style = 0})
		table.insert(list, 1, {id = id, t = os.time()})
	end
	while #list > FEED_LINES do player:hud_remove(table.remove(list).id) end
	restack(player, list)
end

local feed_t = 0
core.register_globalstep(function(dtime)
	feed_t = feed_t + dtime
	if feed_t < 1 then return end
	feed_t = 0
	local now = os.time()
	for name, list in pairs(feeds) do
		local player = core.get_player_by_name(name)
		if player then
			local changed = false
			for i = #list, 1, -1 do
				if now - list[i].t >= FEED_SECONDS then
					player:hud_remove(list[i].id)
					table.remove(list, i)
					changed = true
				end
			end
			if changed then restack(player, list) end
		end
	end
end)

core.register_on_leaveplayer(function(player)
	feeds[player:get_player_name()], xp_hud[player:get_player_name()] = nil, nil
end)

-- XP bar (top-left): "Lv 2  [#####-----]  40/100 XP"
local function xp_text(s)
	local filled = math.floor(10 * s.level_xp / math.max(1, s.next_level_xp))
	return ("Lv %d  [%s%s]  %d/%d XP"):format(s.level, ("#"):rep(filled), ("-"):rep(10 - filled), s.level_xp,
		s.next_level_xp)
end

function npcasso.refresh_player(name)
	npcasso.get(("/player?world=%s&player=%s"):format(npcasso.world(), name), function(s)
		local player = core.get_player_by_name(name)
		if not (s and player) then return end
		npcasso.player_state = npcasso.player_state or {}
		npcasso.player_state[name] = s
		if xp_hud[name] then
			player:hud_change(xp_hud[name], "text", xp_text(s))
		else
			xp_hud[name] = player:hud_add({type = "text", position = {x = 0, y = 0}, alignment = {x = 1, y = 1},
				offset = {x = 16, y = 16}, text = xp_text(s), number = 0x9AE07A, style = 1})
		end
	end)
end

function npcasso.level_up(player, level)
	if type(player) == "string" then player = core.get_player_by_name(player) end
	if not player then return end
	local id = player:hud_add({type = "text", position = {x = 0.5, y = 0.42}, alignment = {x = 0, y = 0},
		text = "Level up!  Lv " .. level, number = 0xFFE066, size = {x = 3}, style = 1})
	core.sound_play("default_place_node_metal", {to_player = player:get_player_name(), gain = 1.0}, true)
	npcasso.feed(player, "Level up! You are now level " .. level .. ".", 0xFFE066)
	core.after(3, function() if player:is_player() then player:hud_remove(id) end end)
end

core.register_on_joinplayer(function(player)
	local name = player:get_player_name()
	core.after(2, npcasso.refresh_player, name)
end)

-- Clock (top-right): "Day 3  ·  14:20  (day)"
local clock_hud, clock_t = {}, 0
local function clock_text(name)
	local t = core.get_timeofday() * 24
	local h, m = math.floor(t), math.floor((t % 1) * 60)
	local part = (h >= 6 and h < 18) and "day" or "night"
	local saved = npcasso.story_clock and npcasso.story_clock[name]
	local day = (saved and saved.day) or (core.get_day_count() + 1)
	return ("Day %d  ·  %02d:%02d  (%s)"):format(day, h, m, part)
end
core.register_globalstep(function(dtime)
	clock_t = clock_t + dtime
	if clock_t < 2 then return end
	clock_t = 0
	for _, p in ipairs(core.get_connected_players()) do
		local name = p:get_player_name()
		local text = clock_text(name)
		if clock_hud[name] then
			p:hud_change(clock_hud[name], "text", text)
		else
			clock_hud[name] = p:hud_add({type = "text", position = {x = 1, y = 0}, alignment = {x = -1, y = 1},
				offset = {x = -16, y = 16}, text = text, number = 0xFFF3DC, style = 1})
		end
	end
end)
core.register_on_leaveplayer(function(p) clock_hud[p:get_player_name()] = nil end)

-- Empty hand: move whatever you hold out of the hotbar into the first free backpack slot.
function npcasso.empty_hand(player)
	local inv, stack = player:get_inventory(), player:get_wielded_item()
	if stack:is_empty() then return "Your hand is already empty." end
	local list = inv:get_list("main")
	for i = player:hud_get_hotbar_itemcount() + 1, #list do
		if list[i]:is_empty() then
			inv:set_stack("main", i, stack)
			player:set_wielded_item(ItemStack(""))
			return "Hand emptied."
		end
	end
	if inv:get_size("backpack") > 0 and inv:room_for_item("backpack", stack) then
		inv:add_item("backpack", stack)
		player:set_wielded_item(ItemStack(""))
		return "Hand emptied."
	end
	return "No free space in your backpack."
end

-- Extra rows under the inventory, so a villager handing you something has somewhere to land.
local BACKPACK = 24

local function ensure_backpack(player)
	local inv = player:get_inventory()
	if inv:get_size("backpack") ~= BACKPACK then inv:set_size("backpack", BACKPACK) end
end

core.register_on_joinplayer(function(player)
	core.after(0.5, function() if player:is_player() then ensure_backpack(player) end end)
end)

if core.get_modpath("sfinv") then
	sfinv.override_page("sfinv:crafting", {
		get = function(self, player, context)
			return sfinv.make_formspec(player, context, [[
				list[current_player;craft;1.75,0.5;3,3;]
				list[current_player;craftpreview;5.75,1.5;1,1;]
				image[4.75,1.5;1,1;sfinv_crafting_arrow.png]
				listring[current_player;main]
				listring[current_player;craft]
				listring[current_player;main]
				listring[current_player;backpack]
			]], true, "size[8,13.2]") ..
				"label[0,9.15;Backpack]list[current_player;backpack;0,9.5;8,3;]"
		end,
	})
end

if core.get_modpath("sfinv_buttons") then
	sfinv_buttons.register_button("npcasso_empty_hand", {
		title = "Empty hand",
		tooltip = "Put away whatever you are holding",
		image = "wieldhand.png",
		action = function(player) npcasso.feed(player, npcasso.empty_hand(player), 0xBBBBBB) end,
	})
end

-- Waypoints: a villager points you somewhere; a marker with the distance shows the way until you arrive.
local PLACE_OFFSETS = {  -- relative to the village square (see town.lua countryside/layout)
	square = {0, 0}, farm = {-11, -11}, pond = {-45, 24}, orchard = {-73, 0}, meadow = {0, 74},
	mine = {70, -55}, wheat_field = {-60, -60},
}
local waypoints = {}  -- player -> {id, pos, t}

local function target_pos(key)
	local o = npcasso.village()
	if not o then return nil end
	local e = npcasso.npc_entity(key)
	if e then return e.object:get_pos() end
	local post = npcasso.posts[key] or (npcasso.landmarks or {})[key]
	if post then return vector.offset(o, post.x, (post.y or 0) + 1, post.z) end
	local off = PLACE_OFFSETS[key]
	if off then return vector.offset(o, off[1], 2, off[2]) end
	if key == "town_hall" and npcasso.landmarks and npcasso.landmarks.townhall then
		local p = npcasso.landmarks.townhall
		return vector.offset(o, p.x, 1, p.z)
	end
end

local LABEL = {square = "Village square", farm = "Village farm", pond = "Pond", orchard = "Apple orchard",
	meadow = "Flower meadow", mine = "The mine", wheat_field = "Wheat field", town_hall = "Town hall"}

function npcasso.point(name, from_npc, key)
	local player = core.get_player_by_name(name)
	local pos = target_pos(key)
	if not (player and pos) then return end
	if waypoints[name] then player:hud_remove(waypoints[name].id) end
	local label = LABEL[key] or npcasso.npc_name(key)
	waypoints[name] = {pos = pos, t = os.time(), key = key, id = player:hud_add({type = "waypoint", name = label,
		text = "m", number = 0xFFD27F, world_pos = pos, precision = 1})}
	npcasso.feed(player, npcasso.npc_name(from_npc) .. " points the way: " .. label, 0xFFD27F)
	-- the villager turns and points (faces the target)
	local e = npcasso.npc_entity(from_npc)
	if e then
		local d = vector.subtract(pos, e.object:get_pos())
		e.object:set_yaw(math.atan2(-d.x, d.z))
	end
end

local wp_t = 0
core.register_globalstep(function(dtime)
	wp_t = wp_t + dtime
	if wp_t < 1 then return end
	wp_t = 0
	for name, w in pairs(waypoints) do
		local p = core.get_player_by_name(name)
		if not p then
			waypoints[name] = nil
		else
			local e = npcasso.npc_entity(w.key)  -- villagers move: follow them
			if e then
				w.pos = e.object:get_pos()
				p:hud_change(w.id, "world_pos", vector.offset(w.pos, 0, 2, 0))
			end
			if vector.distance(p:get_pos(), w.pos) < 5 or os.time() - w.t > 180 then
				p:hud_remove(w.id)
				waypoints[name] = nil
			end
		end
	end
end)

-- An "Empty hand" that lives in hotbar slot 1: select it (press 1) and right-click never places anything.
core.register_craftitem("npcasso:hand", {
	description = "Empty hand (press 1)\nRight-click talks and opens things, never places blocks",
	inventory_image = "wieldhand.png",
	wield_image = "blank.png",
	stack_max = 1,
	groups = {not_in_creative_inventory = 1},
	on_place = function(itemstack, placer, pointed)
		-- still let you use things you point at (chests, doors, boards), just never place a block
		if pointed and pointed.type == "node" then
			local node = core.get_node(pointed.under)
			local def = core.registered_nodes[node.name]
			if def and def.on_rightclick then return def.on_rightclick(pointed.under, node, placer, itemstack, pointed) end
		end
		return itemstack
	end,
	on_drop = function(itemstack) return itemstack end,  -- can't be thrown away
})

local function ensure_hand(player)
	local inv = player:get_inventory()
	if inv:get_stack("main", 1):get_name() == "npcasso:hand" then return end
	for i = 2, inv:get_size("main") do
		if inv:get_stack("main", i):get_name() == "npcasso:hand" then inv:set_stack("main", i, "") end
	end
	local first = inv:get_stack("main", 1)
	inv:set_stack("main", 1, "npcasso:hand")
	if not first:is_empty() then
		local left = inv:add_item("main", first)
		if not left:is_empty() then core.add_item(player:get_pos(), left) end
	end
end

core.register_on_joinplayer(function(player) core.after(1, function() if player:is_player() then ensure_hand(player) end end) end)
core.register_on_respawnplayer(function(player) core.after(0.5, function() if player:is_player() then ensure_hand(player) end end) end)
