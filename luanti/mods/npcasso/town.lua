-- The town: houses for every villager, town hall, pond, sheep pen, crafting table, quest board, journal,
-- per-villager quests, and the Harvest Festival.

local function esc(s) return core.formspec_escape(tostring(s or "")) end
local function plain(s) return (tostring(s or ""):gsub("[<>]", "")) end
local function short(item) return ItemStack(item):get_short_description() end
local BTN = "style_type[button,button_exit;bgcolor=#7a5a33;textcolor=#FFF3DC]"

-- Village layout -----------------------------------------------------------------------------------
-- Every home is built for its owner: different size, materials and details. Coordinates are relative to the
-- village origin (plaza centre); yaw 0 = +z, pi/2 = -x, -pi/2 = +x, pi = -z.

-- Where each villager lives (and returns at night). Elise, Rowan and Mira keep their workplace posts from init.lua.
for id, post in pairs({
	tobin = {x = -11, z = -6, yaw = math.pi},        -- at the farm
	wren = {x = 10, z = -8, yaw = 0},                -- in the town hall
	pip = {x = 2, z = -2, yaw = 0},                  -- on the square
	corin = {x = -16, z = 12, yaw = math.pi / 2},    -- on the pond bank
	lottie = {x = 27, z = 26, yaw = math.pi / 2},    -- by the sheep pen
	bram = {x = 0, z = 21, yaw = math.pi},           -- at his hall door
	nell = {x = 10, z = 19, yaw = math.pi},          -- outside the bakery
	hazel = {x = -10, z = 21, yaw = math.pi},        -- in her garden
	dax = {x = 26, z = -26, yaw = 0},                -- by the mine
}) do npcasso.posts[id] = post end

npcasso.places = {
	{x = 0, z = 0}, {x = 0, z = 7}, {x = -11, z = -7}, {x = 10, z = -5}, {x = -4, z = 0}, {x = -16, z = 12},
	{x = 17, z = 26}, {x = 5, z = 0}, {x = -30, z = -3}, {x = -18, z = 20}, {x = 28, z = -26}, {x = 10, z = 19},
	{x = 17, z = -13}, {x = -3, z = -3}, {x = 3, z = 3}, {x = 0, z = -20}, {x = -20, z = 0},
}

table.insert(npcasso.layout_extras, function(put, box, pick)
	local wood, cobble, glass = pick("default:wood"), pick("default:cobble"), pick("default:glass")
	local torch, lamp = pick("default:torch"), pick("default:meselamp", "default:torch")
	local slab_wood, fence = pick("stairs:slab_wood", "default:wood"), pick("default:fence_wood", "default:wood")
	local bed_b, bed_t = pick("beds:bed_bottom"), pick("beds:bed_top")
	local tree, leaves, apple = pick("default:tree"), pick("default:leaves"), pick("default:apple")
	local ladder = pick("default:ladder_wood")

	local function hollow(x1, y1, z1, x2, y2, z2, wall)  -- walls + floor, empty inside
		box(x1, y1, z1, x2, y2, z2, wall)
		box(x1 + 1, y1, z1 + 1, x2 - 1, y2, z2 - 1, "air")
	end
	local function bed(x, z) if bed_b ~= "air" then put(x, 0, z, bed_b, 0); put(x, 0, z + 1, bed_t, 0) end end

	-- Bram the elder: a big stone-brick hall with bookshelves and glass windows (north).
	local sb = pick("default:stonebrick", "default:cobble")
	box(-4, -1, 22, 4, -1, 29, sb)
	hollow(-4, 0, 22, 4, 4, 29, sb)
	box(-5, 5, 21, 5, 5, 30, pick("stairs:slab_stonebrick", "default:stonebrick"))
	box(0, 0, 22, 0, 1, 22, "air")
	for _, x in ipairs({-2, 2}) do put(x, 2, 22, glass) end
	for _, z in ipairs({24, 27}) do put(-4, 2, z, glass); put(4, 2, z, glass) end
	box(-3, 0, 28, 3, 1, 28, pick("default:bookshelf", "default:wood"))
	bed(-3, 24)
	put(0, 4, 25, lamp)

	-- Nell the baker: red-brick bakery with an oven outside (north-east).
	local brick = pick("default:brick", "default:cobble")
	hollow(8, 0, 20, 13, 3, 24, brick)
	box(8, -1, 20, 13, -1, 24, wood)
	box(7, 4, 19, 14, 4, 25, slab_wood)
	box(10, 0, 20, 10, 1, 20, "air")
	put(12, 1, 20, glass)
	box(13, 4, 24, 13, 6, 24, brick)                     -- chimney
	put(14, 0, 21, pick("default:furnace"))              -- the oven
	put(11, 0, 23, pick("default:chest"))
	bed(9, 22)

	-- Hazel the herbalist: a small leafy hut in a flower garden (north-west).
	hollow(-12, 0, 22, -9, 2, 25, wood)
	box(-13, 3, 21, -8, 3, 26, leaves)
	box(-11, 0, 22, -11, 1, 22, "air")
	bed(-10, 23)
	local garden = {pick("flowers:rose"), pick("flowers:tulip"), pick("flowers:viola"), pick("flowers:dandelion_yellow")}
	for x = -14, -7 do for z = 19, 20 do put(x, 0, z, garden[((x + z) % 4) + 1]) end end

	-- Flower meadow (north-west, around the pond): roses for Hazel's and Mira's quests.
	for x = -26, -14, 2 do
		for z = 15, 28, 3 do put(x, 0, z, garden[((x * 3 + z) % 4) + 1]) end
	end

	-- Pond with Corin's pine shack and a little dock (west).
	box(-23, -2, 9, -16, -1, 15, pick("default:sand"))
	box(-22, -1, 10, -17, -1, 14, pick("default:water_source"))
	box(-23, 0, 9, -16, 0, 15, "air")
	local pine = pick("default:pine_wood", "default:wood")
	hollow(-28, 0, 10, -24, 2, 14, pine)
	box(-29, 3, 9, -23, 3, 15, pick("stairs:slab_pine_wood", "default:pine_wood"))
	box(-24, 0, 12, -24, 1, 12, "air")
	bed(-27, 11)
	box(-21, -1, 12, -19, -1, 12, pine)                  -- dock planks over the water
	put(-19, 0, 12, fence)

	-- Apple orchard (far west): Elise's apples grow here.
	for x = -40, -30, 4 do
		for z = -12, 8, 5 do
			box(x, 0, z, x, 2, z, tree)
			box(x - 1, 3, z - 1, x + 1, 4, z + 1, leaves)
			put(x, 5, z, leaves)
			put(x + 1, 2, z, apple); put(x - 1, 2, z + 1, apple)
		end
	end

	-- Elise's acacia cottage at the orchard's edge (west).
	local acacia = pick("default:acacia_wood", "default:wood")
	hollow(-27, 0, -7, -22, 3, -2, acacia)
	box(-28, 4, -8, -21, 4, -1, pick("stairs:slab_acacia_wood", "default:acacia_wood"))
	box(-22, 0, -5, -22, 1, -5, "air")
	put(-22, 2, -3, glass)
	bed(-26, -6)

	-- Pip's treehouse (south-west): a tall trunk, a platform with railings, a ladder up.
	box(-18, 0, -14, -18, 5, -14, tree)
	box(-20, 6, -16, -16, 6, -12, wood)
	for x = -20, -16 do put(x, 7, -16, fence); put(x, 7, -12, fence) end
	for z = -16, -12 do put(-20, 7, z, fence); put(-16, 7, z, fence) end
	box(-18, 1, -15, -18, 6, -15, ladder)
	box(-21, 8, -17, -15, 9, -11, leaves)
	box(-20, 8, -16, -16, 8, -12, "air")

	-- Tobin's log cabin, hay bales and a second wheat field (south-west).
	hollow(-25, 0, -26, -20, 3, -21, tree)
	box(-26, 4, -27, -19, 4, -20, slab_wood)
	box(-22, 0, -21, -22, 1, -21, "air")
	bed(-24, -25)
	local straw = pick("farming:straw", "default:dry_shrub")
	put(-19, 0, -22, straw); put(-19, 0, -23, straw); put(-19, 1, -22, straw)
	box(-16, -1, -27, -8, -1, -20, pick("farming:soil_wet", "default:dirt"))
	box(-16, 0, -27, -8, 0, -20, pick("farming:wheat_8", "air"))
	box(-12, -1, -27, -12, -1, -20, pick("default:water_source"))
	box(-12, 0, -27, -12, 0, -20, "air")

	-- Lottie's white wool cottage with a red roof, beside a big sheep pen (north-east).
	local wool, red = pick("wool:white", "default:wood"), pick("wool:red", "default:wood")
	hollow(28, 0, 24, 32, 2, 28, wool)
	box(27, 3, 23, 33, 3, 29, red)
	box(28, 0, 26, 28, 1, 26, "air")
	bed(31, 25)
	for x = 17, 26 do put(x, 0, 22, fence); put(x, 0, 31, fence) end
	for z = 22, 31 do put(17, 0, z, fence); put(26, 0, z, fence) end
	put(22, 0, 22, "air")
	box(18, 0, 23, 25, 0, 30, pick("default:grass_3", "air"))

	-- Wren's watchtower (east of the town hall): tall stone tower, ladder inside, lookout on top.
	local cob = pick("default:cobble")
	hollow(16, 0, -15, 18, 7, -13, cob)
	box(17, 0, -15, 17, 1, -15, "air")
	box(17, 1, -14, 17, 7, -14, ladder)
	box(15, 8, -16, 19, 8, -12, wood)
	for x = 15, 19 do put(x, 9, -16, fence); put(x, 9, -12, fence) end
	for z = -16, -12 do put(15, 9, z, fence); put(19, 9, z, fence) end
	put(17, 8, -14, "air")
	put(15, 10, -16, torch, 1); put(19, 10, -12, torch, 1)

	-- Dax's mossy hut and the little mine: coal and iron showing in the rock (south-east).
	local moss = pick("default:mossycobble", "default:cobble")
	hollow(22, 0, -32, 26, 2, -28, moss)
	box(21, 3, -33, 27, 3, -27, moss)
	box(24, 0, -28, 24, 1, -28, "air")
	bed(23, -31)
	local stone = pick("default:stone")
	local coal, iron = pick("default:stone_with_coal", "default:stone"), pick("default:stone_with_iron", "default:stone")
	for h = 0, 3 do box(30 + h, h, -38 + h, 38 - h, h, -30 - h, stone) end
	for i = 0, 7 do
		put(30 + i, 0, -30, i % 2 == 0 and coal or iron)  -- ore along the hill's foot, easy to reach
		put(30, 1, -37 + i, i % 3 == 0 and iron or coal)
	end
	box(33, 0, -30, 34, 1, -32, "air")                    -- the mine mouth
	put(33, 2, -30, torch, 1)

	-- Town hall (south-east of the square): stone floor, wood walls, quest board and crafting table inside.
	box(6, -1, -14, 14, -1, -6, cobble)
	hollow(6, 0, -14, 14, 3, -6, wood)
	box(5, 4, -15, 15, 4, -5, slab_wood)
	box(10, 0, -6, 10, 1, -6, "air")
	for _, x in ipairs({8, 12}) do put(x, 1, -6, glass) end
	put(10, 0, -13, "npcasso:quest_board")
	put(8, 0, -13, "npcasso:crafting_table")
	put(10, 3, -10, lamp)
	put(9, 0, -5, torch, 1); put(11, 0, -5, torch, 1)

	-- Crafting table at Rowan's forge
	put(7, 0, -2, "npcasso:crafting_table")

	-- Lamp posts along the long paths
	for _, d in ipairs({10, 20, 30}) do
		for _, c in ipairs({{2, d}, {-2, -d}, {d, -2}, {-d, 2}}) do
			box(c[1], 0, c[2], c[1], 1, c[2], fence)
			put(c[1], 2, c[2], lamp)
		end
	end
end)

-- Spawn a few sheep in the pen when the village is built (if Animalia is present).
local build = npcasso.build_village
function npcasso.build_village(player, origin)
	build(player, origin)
	core.after(3, function()
		local o = npcasso.village()
		if o and core.registered_entities["animalia:sheep"] then
			for i = 1, 4 do core.add_entity(vector.offset(o, 19 + i, 0.5, 26), "animalia:sheep") end
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
		if fields.quit or fields.close then npcasso.on_talk_closed(name, mine.npc); npcasso.talk[name] = nil end
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
