-- Wordless voices and a few cues. The sound files come from tools/make_sounds.py.

local VOICES = 8
-- {pitch, speed} per villager: low and slow for the old, high and quick for the young.
local VOICE = {elise = {1.15, 1.0}, rowan = {0.7, 0.9}, mira = {1.05, 1.0}, tobin = {0.85, 0.95},
	wren = {0.8, 1.0}, pip = {1.6, 1.3}, bram = {0.6, 0.8}, nell = {1.0, 1.0}, corin = {0.75, 0.9},
	hazel = {1.25, 1.0}, dax = {0.65, 0.85}, lottie = {1.3, 1.05}}
local MOOD = {angry = {0.85, 1.2}, hurt = {0.9, 0.9}, cold = {0.9, 1.05}, afraid = {1.2, 1.35}}
local MAX_SYLLABLES, HEAR = 28, 24

local token = {}  -- npc id -> the line being voiced; a new line cuts the old one

-- One syllable per few letters, a short pause between words, a longer one at a comma or full stop.
local function plan(text)
	local steps, t = {}, 0
	for word in text:gmatch("%S+") do
		local letters = word:gsub("[^%a]", "")
		for i = 1, math.min(3, math.max(1, math.ceil(#letters / 3))) do
			if #steps >= MAX_SYLLABLES then return steps end
			local pick = (letters:byte(math.min(i * 3 - 2, #letters)) or 97) % VOICES + 1
			table.insert(steps, {at = t, voice = pick})
			t = t + 0.075
		end
		t = t + (word:find("[,.;:?!]$") and 0.2 or 0.05)
	end
	return steps
end

-- Who can hear a sound at this spot. Played straight to them: a positional sound is silent when the
-- listener is inside a block, which the village rebuild leaves people in.
local function names_near(pos, range)
	local names = {}
	for _, p in ipairs(core.get_connected_players()) do
		if vector.distance(p:get_pos(), pos) <= range then names[#names + 1] = p:get_player_name() end
	end
	return names
end

local function play_to(sound, names, gain, pitch)
	for _, name in ipairs(names) do
		core.sound_play(sound, {to_player = name, gain = gain, pitch = pitch or 1}, true)
	end
end

function npcasso.speak(npc_id, text)
	local e = npcasso.npc_entity(npc_id)
	if not e or not text or text == "" then return end
	local base, mood = VOICE[npc_id] or {1, 1}, MOOD[npcasso.mood_of(npc_id)] or {1, 1}
	local w = npcasso.winter_now()  -- as winter closes the whole village speaks lower and slower
	local pitch, speed = base[1] * mood[1] * (1 - 0.18 * w), base[2] * mood[2] * (1 - 0.15 * w)
	local last = text:match("([?!.])[%s\"']*$")
	local steps, mine = plan(text), {}
	local heard = names_near(e.object:get_pos(), HEAR)
	if #heard == 0 then return end
	token[npc_id] = mine
	for i, s in ipairs(steps) do
		core.after(s.at / speed, function()
			if token[npc_id] ~= mine then return end
			local p = pitch * (0.94 + math.random() * 0.12)
			local tail = i > #steps - 2
			if tail and last == "?" then p = p * 1.25 elseif tail and last == "." then p = p * 0.9 end
			play_to("npcasso_syl_" .. s.voice, heard, last == "!" and 0.85 or 0.7, p)
		end)
	end
end

local CRIES = {"Aaah!", "Ow! Stop it!", "Help!", "Aaagh!", "Don't!"}

-- The victim of a blow screams, in their own pitch, loud enough for the street to hear. The others gasp.
function npcasso.scream(npc_id, bystanders)
	local e = npcasso.npc_entity(npc_id)
	if not e then return end
	local pitch = math.sqrt((VOICE[npc_id] or {1})[1])
	play_to("npcasso_scream", names_near(e.object:get_pos(), 40), 1, pitch)
	npcasso.bubble(npc_id, CRIES[math.random(#CRIES)], 3, true)
	for _, id in ipairs(bystanders or {}) do
		local b = id ~= npc_id and npcasso.npc_entity(id)
		if b then npcasso.cue("gasp", b.object:get_pos(), 0.5) end
	end
end

-- A cue for one player (name) or for everyone near a position.
function npcasso.cue(sound, where, gain)
	if type(where) == "string" then
		play_to("npcasso_" .. sound, {where}, gain or 0.6, 1)
	elseif where then
		play_to("npcasso_" .. sound, names_near(where, HEAR), gain or 0.6, 1)
	end
end
