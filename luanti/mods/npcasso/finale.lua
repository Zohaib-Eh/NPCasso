-- The ending. From day 7 the backend may say the village has gathered. The player stands with them
-- (the ending plays as a short scene and the run is over) or walks away (the cold keeps coming).
-- No story logic here: the backend sends the words, this file shows them.

local store = npcasso.store
local function plain(s) return (tostring(s or ""):gsub("[<>]", "")) end

local scenes = {}      -- player -> {slides, i, tint}
local offering = {}    -- player -> true while the gathering is open or being answered
local quiet_until = {} -- player -> os.time() before which the gathering is not shown again

local function page(tint, body, buttons)
	return "formspec_version[6]size[12,7]allow_close[false]bgcolor[" .. (tint or "#0c0c10") .. "f2;true]" ..
		"hypertext[1,1;10,3.8;body;" .. core.formspec_escape("<global halign=center color=#EDE5D6>" .. body) .. "]" ..
		buttons
end

local function one_button(id, label)
	return "button[4.5,5.4;3,0.9;" .. id .. ";" .. label .. "]"
end

local function hold(name)
	core.show_formspec(name, "npcasso:hold", page("#0c0c10", "<i>...</i>", ""))
end

local function freeze(player)
	player:set_physics_override({speed = 0, jump = 0})
	player:set_armor_groups({immortal = 1})
end

local function show_slide(name)
	local s = scenes[name]
	if not s then return end
	local slide = s.slides[s.i]
	if slide.kind == "title" then
		return core.show_formspec(name, "npcasso:scene", page(s.tint,
			"<big><big><b>" .. plain(slide.text) .. "</b></big></big>", one_button("leave", "Leave")))
	end
	local body
	if slide.kind == "line" then
		body = "<b>" .. plain(slide.who) .. "</b>\n\n<i>" .. plain(slide.text) .. "</i>"
	else
		body = "<big>" .. plain(slide.text) .. "</big>"
	end
	core.show_formspec(name, "npcasso:scene", page(s.tint, body, one_button("next", "Continue")))
end

-- Called from apply() with the offer text each tick that carries one.
function npcasso.offer_ending(name, text)
	local player = core.get_player_by_name(name)
	if not player or scenes[name] or offering[name] then return end
	if (quiet_until[name] or 0) > os.time() then return end
	offering[name] = true
	core.show_formspec(name, "npcasso:gathering", page("#0c0c10", "<big>" .. plain(text) .. "</big>",
		"button[1.6,5.4;3.6,0.9;stand;Stand with them]button[6.8,5.4;3.6,0.9;walk;Walk away]"))
end

local function answered(name, quiet)
	offering[name] = nil
	quiet_until[name] = os.time() + (quiet or 0)
end

core.register_on_player_receive_fields(function(player, formname, fields)
	local name = player:get_player_name()
	if formname == "npcasso:gathering" then
		if fields.stand then
			hold(name)
			npcasso.post("/ending/accept", {world = npcasso.world(), player = name, game_time = npcasso.game_time()},
				function(out)
					if not (out and out.slides and #out.slides > 0) then
						core.close_formspec(name, "npcasso:hold")
						return answered(name, 60)  -- the moment passes; the village gathers again later
					end
					answered(name)
					local p = core.get_player_by_name(name)
					if not p then return end
					store:set_string("ended:" .. name, out.title)
					npcasso.cold = npcasso.cold or {}
					npcasso.cold[name] = 0
					freeze(p)
					scenes[name] = {slides = out.slides, i = 1, tint = out.tint}
					show_slide(name)
				end, 90)  -- the scene is three model calls in a row
		elseif fields.walk then
			answered(name, 120)
			core.close_formspec(name, "npcasso:gathering")
			npcasso.post("/ending/refuse", {world = npcasso.world(), player = name, game_time = npcasso.game_time()})
		end
	elseif formname == "npcasso:scene" then
		local s = scenes[name]
		if fields.next and s and s.i < #s.slides then
			s.i = s.i + 1
			show_slide(name)
		elseif fields.leave then
			core.disconnect_player(name)
		end
	elseif formname == "npcasso:ended" and fields.leave then
		core.disconnect_player(name)
	end
end)

-- A world whose run has ended keeps its closing card.
core.register_on_joinplayer(function(player)
	local name = player:get_player_name()
	local title = store:get_string("ended:" .. name)
	if title == "" then return end
	core.after(0.5, function()
		if not player:is_player() then return end
		freeze(player)
		core.show_formspec(name, "npcasso:ended", page("#0c0c10",
			"<big><big><b>" .. plain(title) .. "</b></big></big>", one_button("leave", "Leave")))
	end)
end)
