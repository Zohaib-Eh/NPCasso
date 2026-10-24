-- HUD: bottom-left message feed, XP bar, level-up popup.

local FEED_LINES, FEED_SECONDS, LINE_HEIGHT = 6, 8, 22
local feeds = {}   -- player name -> list of {id, t}, newest first
local xp_hud = {}  -- player name -> hud id

local function restack(player, list)
	for i, line in ipairs(list) do
		player:hud_change(line.id, "offset", {x = 12, y = -(i - 1) * LINE_HEIGHT})
	end
end

-- Adds a line to the player's bottom-left feed. Lines fade out after FEED_SECONDS.
function npcasso.feed(player, text, color)
	if type(player) == "string" then player = core.get_player_by_name(player) end
	if not player or not player:is_player() then return end
	local name = player:get_player_name()
	local list = feeds[name] or {}
	feeds[name] = list
	local id = player:hud_add({type = "text", position = {x = 0, y = 0.82}, alignment = {x = 1, y = -1},
		offset = {x = 12, y = 0}, text = text, number = color or 0xFFFFFF, scale = {x = 600, y = 40},
		style = 0})
	table.insert(list, 1, {id = id, t = os.time()})
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
				offset = {x = 12, y = 12}, text = xp_text(s), number = 0x9AE07A, style = 1})
		end
	end)
end

function npcasso.level_up(player, level)
	if type(player) == "string" then player = core.get_player_by_name(player) end
	if not player then return end
	local id = player:hud_add({type = "text", position = {x = 0.5, y = 0.35}, alignment = {x = 0, y = 0},
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
local function clock_text()
	local t = core.get_timeofday() * 24
	local h, m = math.floor(t), math.floor((t % 1) * 60)
	local part = (h >= 6 and h < 18) and "day" or "night"
	return ("Day %d  ·  %02d:%02d  (%s)"):format(core.get_day_count() + 1, h, m, part)
end
core.register_globalstep(function(dtime)
	clock_t = clock_t + dtime
	if clock_t < 2 then return end
	clock_t = 0
	local text = clock_text()
	for _, p in ipairs(core.get_connected_players()) do
		local name = p:get_player_name()
		if clock_hud[name] then
			p:hud_change(clock_hud[name], "text", text)
		else
			clock_hud[name] = p:hud_add({type = "text", position = {x = 1, y = 0}, alignment = {x = -1, y = 1},
				offset = {x = -12, y = 12}, text = text, number = 0xFFF3DC, style = 1})
		end
	end
end)
core.register_on_leaveplayer(function(p) clock_hud[p:get_player_name()] = nil end)
