-- The town: houses for every villager, town hall, pond, sheep pen, crafting table, quest board, journal,
-- per-villager quests, and the Harvest Festival.

local function esc(s) return core.formspec_escape(tostring(s or "")) end
local function plain(s) return (tostring(s or ""):gsub("[<>]", "")) end
local function short(item) return ItemStack(item):get_short_description() end
local BTN = "style_type[button,button_exit;bgcolor=#7a5a33;textcolor=#FFF3DC]"

-- Village layout -----------------------------------------------------------------------------------
-- Buildings are real hand-built schematics from Sokomine's mg_villages (GPL-3.0), loaded from an installed copy
-- of that mod (not shipped in this repo, and its world generation is not enabled). Each building is turned so
-- its door faces the square, and its owner's home spot is right outside that door.

local SCHEMS = core.get_modpath("npcasso") .. "/schems_mgv/"  -- copied from Sokomine/mg_villages (GPL-3.0); git-ignored
local HAVE_SCHEMS = core.read_schematic(SCHEMS .. "well_1.mts", {}) ~= nil

local function store_posts(posts) npcasso.store:set_string("posts", core.serialize(posts)) end
local function load_posts(posts)
	for k, v in pairs(core.deserialize(npcasso.store:get_string("posts")) or {}) do posts[k] = v end
end

-- Blocks the older schematics use that don't exist without mg_villages enabled.
for from, to in pairs({["doors:door_wood_b_1"] = "doors:door_wood_a", ["doors:door_wood_t_1"] = "doors:hidden",
		["doors:door_wood_b_2"] = "doors:door_wood_b", ["doors:door_wood_t_2"] = "doors:hidden",
		["mg_villages:mob_workplace_marker"] = "air"}) do
	if not core.registered_nodes[from] then core.register_alias(from, to) end
end

-- who: villager id whose home this is (post = outside the door); home_only: they keep their work post elsewhere.
local BUILDINGS = {
	{who = "townhall", scm = "chateau_without_garden", yoff = -1, at = {0, -31}},
	{who = "mira", scm = "taverne_1", yoff = 0, at = {0, 31}},
	{who = "bram", scm = "library_1_0", yoff = 0, at = {-24, 26}},
	{who = "nell", scm = "baking_house_1", yoff = 0, at = {22, 26}},
	{who = "rowan", scm = "forge_1", yoff = 0, at = {30, 0}},
	{who = "hazel", scm = "house_with_garden_1_0", yoff = 0, at = {-31, -8}},
	{who = "elise", scm = "small_house_1_0", yoff = 0, at = {-20, -10}, home_only = true},
	{who = "tobin", scm = "house_1_0", yoff = 0, at = {-22, -21}, home_only = true},
	{who = "corin", scm = "logcabin1", yoff = 0, at = {-31, 14}, home_only = true},
	{who = "lottie", scm = "default_town_house_tiny_1", yoff = 1, at = {37, 22}},
	{who = "dax", scm = "default_town_house_small", yoff = -4, at = {29, -23}},
	{who = "wren_tower", scm = "tower_1_0", yoff = 0, at = {18, -14}},
	{scm = "well_1", yoff = 0, at = {-5, 5}},
}

local SIDES = {"+z", "+x", "-z", "-x"}  -- rotating 90 degrees moves one step along this list
local UNIT = {["+z"] = {0, 1}, ["+x"] = {1, 0}, ["-z"] = {0, -1}, ["-x"] = {-1, 0}}
local function index_of(t, v) for i, x in ipairs(t) do if x == v then return i end end end

-- Which side of the schematic its front door is on: among street-level doors (cellars and upper floors
-- ignored), the one nearest an outside wall.
local function door_side(s, yoff)
	local sx, sy, sz = s.size.x, s.size.y, s.size.z
	local street = -yoff + 1  -- schematic row the villagers walk on
	local best, best_d, best_side
	for z = 0, sz - 1 do for y = math.max(0, street - 1), math.min(sy - 1, street + 1) do for x = 0, sx - 1 do
		local n = s.data[(z * sy + y) * sx + x + 1]
		if n and n.name:find("^doors:door") and (n.prob or 255) > 0 then
			local d = {["-x"] = x, ["+x"] = sx - 1 - x, ["-z"] = z, ["+z"] = sz - 1 - z}
			for side, v in pairs(d) do
				if not best_d or v < best_d then best, best_d, best_side = true, v, side end
			end
		end
	end end end
	return best and best_side or "-z"
end

local function toward_square(cx, cz)
	if math.abs(cx) > math.abs(cz) then return cx > 0 and "-x" or "+x" end
	return cz > 0 and "-z" or "+z"
end

-- Places one building; returns the world position just outside its door and the outward unit vector.
local function place_building(o, b)
	local path = SCHEMS .. b.scm .. ".mts"
	local s = core.read_schematic(path, {})
	if not s then return nil end
	local want = toward_square(b.at[1], b.at[2])
	local rot = ((index_of(SIDES, want) - index_of(SIDES, door_side(s, b.yoff))) % 4) * 90
	local unit = UNIT[want]
	local function put_at(r)
		local sx, sz = s.size.x, s.size.z
		if r == 90 or r == 270 then sx, sz = sz, sx end
		local minp = {x = o.x + b.at[1] - math.floor(sx / 2), y = o.y - 1 + b.yoff, z = o.z + b.at[2] - math.floor(sz / 2)}
		local maxp = vector.offset(minp, sx - 1, s.size.y - 1, sz - 1)
		core.place_schematic(minp, path, tostring(r), nil, true)
		-- front door = the street-level door closest to the square
		local doors = core.find_nodes_in_area({x = minp.x, y = o.y - 1, z = minp.z}, {x = maxp.x, y = o.y + 1, z = maxp.z},
			{"group:door"})
		table.sort(doors, function(a, c)
			return (a.x - o.x) ^ 2 + (a.z - o.z) ^ 2 < (c.x - o.x) ^ 2 + (c.z - o.z) ^ 2
		end)
		return doors[1], minp, maxp
	end
	local door, minp, maxp = put_at(rot)
	local center = {x = o.x + b.at[1], z = o.z + b.at[2]}
	local function dist2(p) return (p.x - o.x) ^ 2 + (p.z - o.z) ^ 2 end
	if not door or dist2(door) > dist2(center) then  -- rotation guess was backwards: turn it around
		door, minp, maxp = put_at((rot + 180) % 360)
	end
	local out
	if door then
		out = {x = door.x + unit[1], y = o.y, z = door.z + unit[2]}
	else
		out = {x = center.x + unit[1] * 8, y = o.y, z = center.z + unit[2] * 8}
	end
	return out, unit
end

-- Finds the ground surface (top walkable, non-plant node) at x,z.
local function surface(x, z, top, bottom)
	for y = top, bottom, -1 do
		local n = core.get_node({x = x, y = y, z = z}).name
		local def = core.registered_nodes[n]
		if def and def.walkable and not n:find("leaves") and not n:find("tree") and not n:find("log") then return y end
	end
end

-- Quest resources live out in the countryside (between the village and the soft border).
local function countryside(o)
	local function at(dx, dz) local y = surface(o.x + dx, o.z + dz, o.y + 25, o.y - 25); return y end
	local function set(dx, y, dz, name) core.set_node({x = o.x + dx, y = y, z = o.z + dz}, {name = name}) end
	local tree, leaves, apple = "default:tree", "default:leaves", "default:apple"
	-- Apple orchard, far west
	for dx = -80, -66, 5 do
		for dz = -12, 12, 6 do
			local y = at(dx, dz)
			if y then
				for h = 1, 3 do set(dx, y + h, dz, tree) end
				for ax = -1, 1 do for az = -1, 1 do for ay = 4, 5 do set(dx + ax, y + ay, dz + az, leaves) end end end
				set(dx, y + 6, dz, leaves)
				set(dx + 1, y + 3, dz, apple); set(dx - 1, y + 3, dz + 1, apple)
			end
		end
	end
	-- Flower meadow, far north
	local flowers = {"flowers:rose", "flowers:tulip", "flowers:viola", "flowers:dandelion_yellow", "flowers:rose"}
	for dx = -14, 14, 2 do
		for dz = 66, 82, 2 do
			local y = at(dx, dz)
			if y then set(dx, y + 1, dz, flowers[((dx + dz) % 5) + 1]) end
		end
	end
	-- Dax's mine hill with coal and iron showing, far south-east
	local base = at(70, -55) or o.y - 1
	for h = 0, 4 do
		for dx = 64 + h, 76 - h do for dz = -61 + h, -49 - h do set(dx, base + 1 + h, dz, "default:stone") end end
	end
	for i = 0, 12 do
		set(64 + i, base + 1, -49, i % 2 == 0 and "default:stone_with_coal" or "default:stone_with_iron")
		set(64, base + 1 + (i % 3), -61 + i, i % 3 == 0 and "default:stone_with_iron" or "default:stone_with_coal")
	end
	set(70, base + 6, -55, "default:torch")
	-- Big wheat field, far south-west (flattened to one level, with a water channel)
	local fy = at(-60, -60) or o.y - 1
	for dx = -66, -54 do
		for dz = -66, -54 do
			for y = fy + 1, fy + 6 do set(dx, y, dz, "air") end
			if dx == -60 then set(dx, fy, dz, "default:water_source")
			else set(dx, fy, dz, "farming:soil_wet"); set(dx, fy + 1, dz, "farming:wheat_8") end
		end
	end
end

-- Run by build_village after the base layout, before villagers are spawned.
function npcasso.after_layout(o)
	if HAVE_SCHEMS then
		for _, b in ipairs(BUILDINGS) do
			local out, unit = place_building(o, b)
			if out then
				local rel = {x = out.x - o.x, z = out.z - o.z, yaw = math.atan2(-unit[1], unit[2])}
				local side = {x = unit[2], z = -unit[1]}  -- along the front wall
				if b.who == "townhall" then
					core.set_node(vector.offset(out, side.x * 2, 0, side.z * 2), {name = "npcasso:quest_board"})
					core.set_node(vector.offset(out, -side.x * 2, 0, -side.z * 2), {name = "npcasso:crafting_table"})
					npcasso.posts.wren = {x = rel.x + side.x * 3, z = rel.z + side.z * 3, yaw = rel.yaw}
				elseif b.who == "rowan" then
					core.set_node(vector.offset(out, side.x * 2, 0, side.z * 2), {name = "cottages:anvil"})
					core.set_node(vector.offset(out, -side.x * 2, 0, -side.z * 2), {name = "npcasso:crafting_table"})
					npcasso.posts.rowan = rel
				elseif b.who and npcasso.posts and not b.home_only and b.who ~= "wren_tower" then
					npcasso.posts[b.who] = rel
				end
			end
		end
	else
		core.log("warning", "[npcasso] mg_villages schematics not found at " .. SCHEMS .. "; village has no houses")
	end
	countryside(o)
	npcasso.save_posts()
end

-- Villagers' home spots (computed from where the doors ended up) are saved with the world.
function npcasso.save_posts() store_posts(npcasso.posts) end

-- Other villagers' spots that aren't tied to a building.
for id, post in pairs({
	tobin = {x = -11, z = -6, yaw = math.pi},        -- at the village farm
	pip = {x = 2, z = -2, yaw = 0},                  -- on the square
	corin = {x = -16, z = 12, yaw = math.pi / 2},    -- on the pond bank
	wren = {x = 0, z = -14, yaw = math.pi},          -- until the town hall is placed
}) do npcasso.posts[id] = post end
load_posts(npcasso.posts)

npcasso.places = {
	{x = 0, z = 0}, {x = -4, z = 0}, {x = -5, z = 9}, {x = -11, z = -7}, {x = 0, z = -12}, {x = 0, z = 12},
	{x = 12, z = 0}, {x = -12, z = 0}, {x = -16, z = 12}, {x = 30, z = 32}, {x = 14, z = 12},
}

table.insert(npcasso.layout_extras, function(put, box, pick)
	local wood, fence = pick("default:wood"), pick("default:fence_wood", "default:wood")
	local tree, leaves = pick("default:tree"), pick("default:leaves")
	local ladder = pick("default:ladder_wood")

	-- Pond with a little dock (west) by Corin's cabin
	box(-23, -2, 9, -16, -1, 15, pick("default:sand"))
	box(-22, -1, 10, -17, -1, 14, pick("default:water_source"))
	box(-23, 0, 9, -16, 0, 15, "air")
	box(-21, -1, 12, -19, -1, 12, pick("default:pine_wood", "default:wood"))
	put(-19, 0, 12, fence)

	-- Pip's treehouse (north-east of the square): a tall trunk, a platform with railings, a ladder up.
	local tx, tz = 14, 12
	box(tx, 0, tz, tx, 5, tz, tree)
	box(tx - 2, 6, tz - 2, tx + 2, 6, tz + 2, wood)
	for x = tx - 2, tx + 2 do put(x, 7, tz - 2, fence); put(x, 7, tz + 2, fence) end
	for z = tz - 2, tz + 2 do put(tx - 2, 7, z, fence); put(tx + 2, 7, z, fence) end
	box(tx, 1, tz - 1, tx, 6, tz - 1, ladder)
	box(tx - 3, 8, tz - 3, tx + 3, 9, tz + 3, leaves)
	box(tx - 2, 8, tz - 2, tx + 2, 8, tz + 2, "air")

	-- Sheep pen by Lottie's cottage (north-east)
	for x = 26, 35 do put(x, 0, 30, fence); put(x, 0, 39, fence) end
	for z = 30, 39 do put(26, 0, z, fence); put(35, 0, z, fence) end
	put(30, 0, 30, "air")
end)

-- Spawn a few sheep in the pen when the village is built (if Animalia is present).
local build = npcasso.build_village
function npcasso.build_village(player, origin)
	build(player, origin)
	core.after(3, function()
		local o = npcasso.village()
		if o and core.registered_entities["animalia:sheep"] then
			for i = 1, 4 do core.add_entity(vector.offset(o, 28 + i, 0.5, 34), "animalia:sheep") end
		end
	end)
end

-- Crafting table ----------------------------------------------------------------------------------

local CRAFT_FS = "formspec_version[6]size[10.5,10]" ..
	"label[0.4,0.5;Crafting Table]" ..
	"list[current_player;craft;1.6,1;3,3;]" ..
	"image[5.5,2.25;1,1;gui_furnace_arrow_bg.png^[transformR270]" ..
	"list[current_player;craftpreview;7,2.25;1,1;]" ..
	"list[current_player;main;0.4,5;8,1;]" ..
	"list[current_player;main;0.4,6.35;8,3;8]" ..
	"listring[current_player;main]listring[current_player;craft]"

core.register_node("npcasso:crafting_table", {
	description = "Crafting Table",
	tiles = {"default_wood.png^default_tool_steelpick.png", "default_wood.png", "default_tree.png"},
	groups = {choppy = 2, oddly_breakable_by_hand = 2, flammable = 2},
	on_construct = function(pos)
		core.get_meta(pos):set_string("formspec", CRAFT_FS)
		core.get_meta(pos):set_string("infotext", "Crafting Table")
	end,
})
core.register_craft({output = "npcasso:crafting_table",
	recipe = {{"group:wood", "group:wood"}, {"group:wood", "group:wood"}}})

-- Quest board, journal, per-villager quests ------------------------------------------------------------

local function quest_row(y, q, button)
	local icon = q.item and core.registered_items[q.item] and ("item_image[0.3," .. y .. ";0.9,0.9;" .. q.item .. "]")
		or ("image[0.3," .. y .. ";0.9,0.9;default_tool_steelsword.png]")
	local reward = {}
	for _, r in ipairs(q.reward or {}) do
		local stack = type(r) == "string" and ItemStack(r) or ItemStack(r.item .. " " .. (r.count or 1))
		table.insert(reward, stack:get_count() .. " " .. stack:get_short_description())
	end
	local line = (q.npc or "") .. (q.progress and ("  ·  " .. q.progress) or "") ..
		(#reward > 0 and ("  ·  reward: " .. table.concat(reward, ", ")) or "") .. (q.xp and ("  ·  " .. q.xp .. " XP") or "")
	return icon ..
		"label[1.4," .. (y + 0.25) .. ";" .. esc((q.main and "* " or "") .. q.title) .. "]" ..
		"label[1.4," .. (y + 0.7) .. ";" .. esc(line) .. "]" .. (button or "")
end

local function quests_fs(title, rows, footer)
	local h = math.max(1, #rows) * 1.25
	local fs = "formspec_version[6]size[14,11]" .. BTN ..
		"hypertext[0.4,0.3;13,0.8;t;" .. esc("<big><b>" .. plain(title) .. "</b></big>") .. "]" ..
		"box[0.3,1.1;13.4,7.9;#00000055]" ..
		"scroll_container[0.4,1.2;12.6,7.7;qscroll;vertical;0.1]"
	for i, r in ipairs(rows) do fs = fs .. r((i - 1) * 1.25 + 0.1) end
	if #rows == 0 then fs = fs .. "label[0.3,0.5;Nothing here yet.]" end
	fs = fs .. "scroll_container_end[]" ..
		"scrollbaroptions[max=" .. math.max(0, math.floor((h - 7.5) * 10)) .. "]" ..
		"scrollbar[13.1,1.2;0.4,7.7;vertical;qscroll;0]" .. (footer or "")
	return fs
end

local board_cache = {}

function npcasso.show_board(name)
	npcasso.get(("/quests?world=%s&player=%s"):format(npcasso.world(), name), function(q)
		npcasso.get(("/festival?world=%s&player=%s"):format(npcasso.world(), name), function(f)
			if not q then return core.chat_send_player(name, "The quest board is blank... (backend unreachable)") end
			board_cache[name] = q
			local rows = {}
			for i, a in ipairs(q.available) do
				table.insert(rows, function(y) return quest_row(y, a, "button[11,"..(y + 0.15)..";1.5,0.7;accept_"..i..";Accept]") end)
			end
			for _, a in ipairs(q.journal.active) do
				table.insert(rows, function(y) return quest_row(y, a, "label[11.1,"..(y + 0.45)..";Active]") end)
			end
			local footer
			if f and f.held then
				footer = "label[0.4,9.6;The Harvest Festival has been held.]"
			elseif f and f.eligible then
				footer = "button[0.4,9.3;5,1;festival;Begin the Harvest Festival]"
			elseif f then
				footer = "label[0.4,9.4;" .. esc(("Harvest Festival: reach Lv %d (you are Lv %d) and finish %d main quest(s) (*)."):format(
					f.level_needed, f.level, #f.missing_main)) .. "]"
			end
			core.show_formspec(name, "npcasso:board", quests_fs("Village Quest Board", rows,
				(footer or "") .. "button_exit[11,9.4;2.5,0.9;close;Close]"))
		end)
	end)
end

function npcasso.show_journal(name)
	npcasso.get(("/quests?world=%s&player=%s"):format(npcasso.world(), name), function(q)
		if not q then return end
		local rows = {}
		for _, a in ipairs(q.journal.active) do table.insert(rows, function(y) return quest_row(y, a) end) end
		for _, a in ipairs(q.journal.done) do
			table.insert(rows, function(y) return quest_row(y, {title = a.title .. "  (done)", npc = a.npc, item = a.item}) end)
		end
		core.show_formspec(name, "npcasso:journal", quests_fs("Journal", rows, "button_exit[11,9.4;2.5,0.9;close;Close]"))
	end)
end

local npcq = {}  -- player -> {npc, available, active}

function npcasso.show_npc_quests(player, npc_id)
	local name = player:get_player_name()
	npcasso.get(("/quests?world=%s&player=%s"):format(npcasso.world(), name), function(q)
		if not q then return end
		local mine = {npc = npc_id, available = {}, active = {}}
		for _, a in ipairs(q.available) do if a.npc_id == npc_id then table.insert(mine.available, a) end end
		for _, a in ipairs(q.journal.active) do if a.npc_id == npc_id then table.insert(mine.active, a) end end
		npcq[name] = mine
		local rows = {}
		for i, a in ipairs(mine.available) do
			table.insert(rows, function(y) return quest_row(y, a, "button[11,"..(y + 0.15)..";1.5,0.7;accept_"..i..";Accept]") end)
		end
		for _, a in ipairs(mine.active) do
			table.insert(rows, function(y) return quest_row(y, a, a.item and "label[11.1,"..(y + 0.45)..";Active]" or "") end)
		end
		local footer = BTN .. "button[0.4,9.4;3,0.9;back;Back]" ..
			(#mine.active > 0 and "button[3.7,9.4;3.5,0.9;handin;Hand in items]" or "") ..
			"button_exit[11,9.4;2.5,0.9;close;Close]"
		core.show_formspec(name, "npcasso:npcquests", quests_fs(npcasso.npc_name(npc_id) .. "'s requests", rows, footer))
	end)
end

local function handin(player, npc_id)
	local name, inv = player:get_player_name(), player:get_inventory()
	local items = {}
	for _, a in ipairs((npcq[name] or {}).active or {}) do
		if a.item then
			local n = 0
			for _, stack in ipairs(inv:get_list("main")) do
				if stack:get_name() == a.item then n = n + stack:get_count() end
			end
			items[a.item] = n
		end
	end
	npcasso.post("/quest/handin", {world = npcasso.world(), player = name, npc_id = npc_id, items = items,
		game_time = npcasso.game_time()}, function(out)
		if not out then return end
		for item, n in pairs(out.consumed or {}) do inv:remove_item("main", ItemStack(item .. " " .. n)) end
		if next(out.consumed or {}) == nil then npcasso.feed(player, "You don't have what they asked for yet.", 0xBBBBBB) end
		npcasso.apply(name, out)
		npcasso.show_npc_quests(player, npc_id)
	end)
end

local function accept(player, quest, reopen)
	local name = player:get_player_name()
	npcasso.post("/quest/accept", {world = npcasso.world(), player = name, quest_id = quest.id}, function(out)
		if out then npcasso.feed(player, "New quest: " .. quest.title, 0x9AD0FF) end
		reopen()
	end)
end

core.register_on_player_receive_fields(function(player, formname, fields)
	local name = player:get_player_name()
	if formname == "npcasso:board" then
		for k in pairs(fields) do
			local i = tonumber(k:match("^accept_(%d+)$") or "")
			if i and board_cache[name] then
				accept(player, board_cache[name].available[i], function() npcasso.show_board(name) end)
			end
		end
		if fields.festival then npcasso.begin_festival(player) end
		return true
	elseif formname == "npcasso:npcquests" then
		local mine = npcq[name]
		if not mine then return true end
		for k in pairs(fields) do
			local i = tonumber(k:match("^accept_(%d+)$") or "")
			if i then accept(player, mine.available[i], function() npcasso.show_npc_quests(player, mine.npc) end) end
		end
		if fields.handin then handin(player, mine.npc) end
		if fields.back then npcasso.open_talk(player, mine.npc) end
		if fields.quit or fields.close then npcasso.on_talk_closed(name, mine.npc); npcasso.save_chat(name); npcasso.talk[name] = nil end
		return true
	elseif formname == "npcasso:journal" then
		return true
	end
end)

core.register_node("npcasso:quest_board", {
	description = "Village Quest Board",
	tiles = {"default_wood.png", "default_wood.png", "default_wood.png", "default_wood.png", "default_wood.png",
		"default_wood.png^default_paper.png"},
	paramtype2 = "facedir",
	groups = {choppy = 2, oddly_breakable_by_hand = 2},
	on_construct = function(pos) core.get_meta(pos):set_string("infotext", "Village Quest Board (right-click)") end,
	on_rightclick = function(pos, node, clicker)
		if clicker and clicker:is_player() then npcasso.show_board(clicker:get_player_name()) end
	end,
})

core.register_craftitem("npcasso:journal", {
	description = "Journal",
	inventory_image = "default_book_written.png",
	stack_max = 1,
	on_use = function(itemstack, user)
		if user and user:is_player() then npcasso.show_journal(user:get_player_name()) end
	end,
})

-- Harvest Festival ------------------------------------------------------------------------------------

local fest = {}  -- player -> {votes, ending, i, speeches = {}}
local VOTE_COLOR = {["for"] = "#7CE07C", abstain = "#BBBBBB", against = "#FF7A7A"}
local VOTE_WORD = {["for"] = "votes FOR you", abstain = "abstains", against = "votes AGAINST you"}
local ENDING = {
	hero = {"Hero of the Village", "The square erupts in cheers. Whatever you did here, they will tell stories about it."},
	accepted = {"Accepted", "Not everyone is convinced, but the village makes room for you. It is a start."},
	turned_away = {"Turned Away", "The village has remembered too much. Bram hands you your pack and points to the road."},
}

local function fetch_speech(name, i)
	local f = fest[name]
	if not f or i > #f.votes or f.speeches[i] then return end
	f.speeches[i] = false  -- requested
	npcasso.post("/festival/speech", {world = npcasso.world(), player = name, npc_id = f.votes[i].npc_id}, function(out)
		if not fest[name] then return end
		f.speeches[i] = out and out.speech or "..."
		if f.i == i then npcasso.show_festival(name) end
	end)
end

function npcasso.show_festival(name)
	local f = fest[name]
	if not f then return end
	local fs = "formspec_version[6]size[13,9]" .. BTN .. "box[0,0;13,9;#1c140c]"
	if f.i > #f.votes then
		local e = ENDING[f.ending] or ENDING.accepted
		local tally = {["for"] = 0, abstain = 0, against = 0}
		for _, v in ipairs(f.votes) do tally[v.vote] = tally[v.vote] + 1 end
		fs = fs .. "hypertext[0.5,1;12,6;end;" .. esc("<global halign=center color=#FFF3DC><big><b>The Harvest Festival</b></big>\n\n" ..
			"<style size=30 color=#FFE066><b>" .. e[1] .. "</b></style>\n\n" .. e[2] .. "\n\n" ..
			("<style color=#BBBBBB>%d for · %d abstained · %d against</style>"):format(tally["for"], tally.abstain, tally.against)) .. "]" ..
			"button_exit[4.5,7.6;4,0.9;close;Close]"
	else
		local v = f.votes[f.i]
		local info = npcasso.npcs[v.npc_id] or {}
		local speech = f.speeches[f.i]
		fs = fs .. "model[0.4,0.6;3.6,6.8;p;character.b3d;" .. esc(info.skin or "character.png") .. ";-5,200;false;true;0,79;30]" ..
			"hypertext[4.3,0.6;8.3,6.6;s;" .. esc("<global color=#FFF3DC size=18><big><b>" .. plain(v.name) ..
			"</b></big>  <style color=#BBBBBB>" .. plain(info.role or "") .. "</style>\n\n" ..
			"<style color=" .. VOTE_COLOR[v.vote] .. "><b>" .. VOTE_WORD[v.vote] .. "</b></style>\n\n" ..
			(speech and ("\"" .. plain(speech) .. "\"") or "<i><style color=#BBBBBB>" .. plain(v.name) .. " is gathering their thoughts...</style></i>")) .. "]" ..
			"label[0.5,8.2;" .. esc(("Villager %d of %d"):format(f.i, #f.votes)) .. "]" ..
			"button[9,7.8;3.5,0.9;next;" .. (f.i == #f.votes and "The verdict" or "Next") .. "]"
	end
	core.show_formspec(name, "npcasso:festival", fs)
end

function npcasso.begin_festival(player)
	local name = player:get_player_name()
	npcasso.post("/festival", {world = npcasso.world(), player = name, game_time = npcasso.game_time()}, function(out)
		if not out then return core.chat_send_player(name, "The festival can't begin yet.") end
		fest[name] = {votes = out.votes, ending = out.ending, i = 1, speeches = {}}
		fetch_speech(name, 1)
		fetch_speech(name, 2)  -- prepare the next speech while the first is read
		npcasso.show_festival(name)
	end)
end

core.register_on_player_receive_fields(function(player, formname, fields)
	if formname ~= "npcasso:festival" then return end
	local name = player:get_player_name()
	local f = fest[name]
	if f and fields.next then
		f.i = f.i + 1
		fetch_speech(name, f.i)
		fetch_speech(name, f.i + 1)
		npcasso.show_festival(name)
	end
	return true
end)

-- Starter kit gains the journal; command shortcuts.
local kit = npcasso.give_starter_kit
function npcasso.give_starter_kit(player)
	kit(player)
	local inv = player:get_inventory()
	if not inv:contains_item("main", "npcasso:journal") then inv:add_item("main", "npcasso:journal") end
end
