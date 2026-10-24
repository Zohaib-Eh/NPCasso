-- The town: houses for every villager, town hall, pond, sheep pen, crafting table, quest board, journal,
-- per-villager quests, and the Harvest Festival.

local function esc(s) return core.formspec_escape(tostring(s or "")) end
local function plain(s) return (tostring(s or ""):gsub("[<>]", "")) end
local function short(item) return ItemStack(item):get_short_description() end
local BTN = "style_type[button,button_exit;bgcolor=#7a5a33;textcolor=#FFF3DC]"

-- Village layout -----------------------------------------------------------------------------------

-- House plots (south-west corner of a 5x5 hut) and which side the door faces the square from.
local HOUSES = {
	nell = {x = -16, z = 20, door = "s"}, hazel = {x = -6, z = 20, door = "s"},
	bram = {x = 14, z = 20, door = "s"}, mira = {x = 4, z = 20, door = "s"},
	tobin = {x = -16, z = -24, door = "n"}, lottie = {x = -6, z = -24, door = "n"},
	corin = {x = 4, z = -24, door = "n"}, dax = {x = 14, z = -24, door = "n"},
	rowan = {x = 20, z = -6, door = "w"}, wren = {x = 20, z = 4, door = "w"},
	elise = {x = -24, z = -6, door = "e"}, pip = {x = -24, z = 4, door = "e"},
}
local DOOR = {s = {2, -1, 0}, n = {2, 5, math.pi}, w = {-1, 2, math.pi / 2}, e = {5, 2, -math.pi / 2}}

-- Villagers without a workplace live at their house door; the others keep their v1 workplace posts.
for id, h in pairs(HOUSES) do
	if not npcasso.posts[id] then
		local d = DOOR[h.door]
		npcasso.posts[id] = {x = h.x + d[1], z = h.z + d[2], yaw = d[3]}
	end
end
npcasso.posts.tobin = {x = -11, z = -6, yaw = math.pi}     -- at the farm
npcasso.posts.wren = {x = 10, z = -8, yaw = 0}             -- in the town hall
npcasso.posts.pip = {x = 2, z = -2, yaw = 0}               -- on the square
npcasso.posts.corin = {x = -12, z = 12, yaw = 0}           -- by the pond
npcasso.posts.lottie = {x = 11, z = 7, yaw = math.pi}      -- by the sheep pen

npcasso.places = {
	{x = 0, z = 0}, {x = 0, z = 7}, {x = -11, z = -7}, {x = 10, z = -5}, {x = -4, z = 0}, {x = -12, z = 12},
	{x = 11, z = 7}, {x = 5, z = 0}, {x = -3, z = -3}, {x = 3, z = 3},
}
for _, h in pairs(HOUSES) do
	local d = DOOR[h.door]
	table.insert(npcasso.places, {x = h.x + d[1], z = h.z + d[2]})
end

table.insert(npcasso.layout_extras, function(put, box, pick)
	local wood, cobble, glass = pick("default:wood"), pick("default:cobble"), pick("default:glass")
	local torch, lamp = pick("default:torch"), pick("default:meselamp", "default:torch")
	local slab_wood, fence = pick("stairs:slab_wood", "default:wood"), pick("default:fence_wood", "default:wood")
	local bed_b, bed_t = pick("beds:bed_bottom"), pick("beds:bed_top")

	-- Houses: 5x5 huts, cobble base, wood walls, slab roof, door gap facing the square, bed and torch inside.
	for _, h in pairs(HOUSES) do
		local x, z = h.x, h.z
		box(x, -1, z, x + 4, -1, z + 4, wood)
		box(x, 0, z, x + 4, 0, z + 4, cobble)
		box(x, 1, z, x + 4, 2, z + 4, wood)
		box(x + 1, 0, z + 1, x + 3, 2, z + 3, "air")
		box(x - 1, 3, z - 1, x + 5, 3, z + 5, slab_wood)
		local dx, dz = ({s = {2, 0}, n = {2, 4}, w = {0, 2}, e = {4, 2}})[h.door][1],
			({s = {2, 0}, n = {2, 4}, w = {0, 2}, e = {4, 2}})[h.door][2]
		box(x + dx, 0, z + dz, x + dx, 1, z + dz, "air")
		put(x + 2, 1, z + (h.door == "s" and 4 or 0), glass)
		if bed_b ~= "air" then put(x + 1, 0, z + 1, bed_b, 0); put(x + 1, 0, z + 2, bed_t, 0) end
		put(x + 3, 0, z + 3, torch, 1)
	end

	-- Town hall (south-east of the square): stone floor, wood walls, door facing the square.
	box(6, -1, -14, 14, -1, -6, cobble)
	box(6, 0, -14, 14, 3, -14, wood)
	box(6, 0, -6, 14, 3, -6, wood)
	box(6, 0, -14, 6, 3, -6, wood)
	box(14, 0, -14, 14, 3, -6, wood)
	box(6, 4, -14, 14, 4, -6, slab_wood)
	box(10, 0, -6, 10, 1, -6, "air")
	for _, x in ipairs({8, 12}) do put(x, 1, -6, glass) end
	put(10, 0, -13, "npcasso:quest_board")
	put(8, 0, -13, "npcasso:crafting_table")
	put(10, 3, -10, lamp)
	put(9, 0, -5, torch, 1); put(11, 0, -5, torch, 1)

	-- Crafting table at Rowan's forge
	put(7, 0, -2, "npcasso:crafting_table")

	-- Pond (north-west) for Corin
	box(-15, -2, 13, -10, -1, 17, pick("default:sand"))
	box(-14, -1, 14, -11, -1, 16, pick("default:water_source"))

	-- Sheep pen (north-east) for Lottie
	for x = 8, 15 do put(x, 0, 9, fence); put(x, 0, 15, fence) end
	for z = 9, 15 do put(8, 0, z, fence); put(15, 0, z, fence) end
	put(11, 0, 9, "air")
end)

-- Spawn a few sheep in the pen when the village is built (if Animalia is present).
local build = npcasso.build_village
function npcasso.build_village(player, origin)
	build(player, origin)
	core.after(3, function()
		local o = npcasso.village()
		if o and core.registered_entities["animalia:sheep"] then
			for i = 1, 3 do core.add_entity(vector.offset(o, 10 + i, 0.5, 12), "animalia:sheep") end
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
