-- Village life: roaming, motives (moods), face-to-face gossip, auto-talk, monsters, harvests.
-- Moods come from the backend and only drive behaviour; the player never sees them.

local WALK_SPEED, FLEE_SPEED = 1.5, 2.4
local MEET_RANGE, PAIR_COOLDOWN, MEET_SECONDS = 3, 60, 7
local EARSHOT, VOICED_GOSSIP_COOLDOWN = 16, 20   -- LLM-voiced gossip only when a player can hear it
local AUTOTALK_RANGE, AUTOTALK_COS, AUTOTALK_HOLD, AUTOTALK_BLOCK = 2.5, 0.707, 1.0, 60
local SAFE_RADIUS = 34

npcasso.moods = {}
local pair_cooldown, last_voiced = {}, 0

local function now() return os.time() end

local function set_walking(self, walking)
	if self.walking == walking then return end
	self.walking = walking
	self.object:set_animation(walking and npcasso.ANIM_WALK or npcasso.ANIM_STAND, 30, 0)
end

local function halt(self)
	local v = self.object:get_velocity()
	self.object:set_velocity({x = 0, y = v.y, z = 0})
	set_walking(self, false)
end

local function face(self, target)
	local d = vector.subtract(target, self.object:get_pos())
	self.object:set_yaw(math.atan2(-d.x, d.z))
end

local function nearest_player(pos)
	local best, bd
	for _, p in ipairs(core.get_connected_players()) do
		local d = vector.distance(p:get_pos(), pos)
		if not bd or d < bd then best, bd = p, d end
	end
	return best, bd
end

-- Village places villagers wander between (absolute positions).
local function village_places()
	local o = npcasso.village()
	if not o then return {} end
	local list = {}
	for _, p in ipairs(npcasso.places or {}) do table.insert(list, vector.offset(o, p.x, 0, p.z)) end
	for _, post in pairs(npcasso.posts) do table.insert(list, vector.offset(o, post.x, 0, post.z)) end
	return list
end

local function is_day()
	local t = core.get_timeofday()
	return t > 0.23 and t < 0.77
end

-- Moods -------------------------------------------------------------------------------------------

local moods_at = 0
function npcasso.refresh_moods()
	if now() - moods_at < 3 then return end
	moods_at = now()
	local p = core.get_connected_players()[1]
	if not p then return end
	npcasso.get(("/moods?world=%s&player=%s&game_time=%.3f"):format(npcasso.world(), p:get_player_name(),
		npcasso.game_time()), function(m) if m then npcasso.moods = m end end)
end

local mood_t = 0
core.register_globalstep(function(dtime)
	mood_t = mood_t + dtime
	if mood_t < 15 then return end
	mood_t = 0
	npcasso.refresh_moods()
end)

-- Meetings and gossip -----------------------------------------------------------------------------

local function show_gossip(teller, listener, out, audible_players)
	if not (out and out.line) then return end
	npcasso.bubble(teller.npc_id, out.line, 6)
	for _, p in ipairs(audible_players) do
		npcasso.feed(p, npcasso.npc_name(teller.npc_id) .. " to " .. npcasso.npc_name(listener.npc_id) .. ": " .. out.line,
			0xD8C8FF)
	end
	core.after(3, function()
		if not listener.object:get_pos() then return end
		npcasso.bubble(listener.npc_id, out.reply, 5)
		for _, p in ipairs(audible_players) do
			if p:is_player() then npcasso.feed(p, npcasso.npc_name(listener.npc_id) .. ": " .. out.reply, 0xD8C8FF) end
		end
	end)
end

local function start_meeting(a, b)
	local t = now() + MEET_SECONDS
	a.meet_until, b.meet_until = t, t
	halt(a); halt(b)
	face(a, b.object:get_pos()); face(b, a.object:get_pos())
	for _, p in ipairs(core.get_connected_players()) do
		local name = p:get_player_name()
		local audible = vector.distance(p:get_pos(), a.object:get_pos()) < EARSHOT
			and now() - last_voiced >= VOICED_GOSSIP_COOLDOWN
		if audible then last_voiced = now() end
		local listeners = audible and {p} or {}
		local function ask(teller, listener, then_cb)
			npcasso.post("/gossip", {world = npcasso.world(), player = name, teller = teller.npc_id,
				listener = listener.npc_id, game_time = npcasso.game_time(), audible = audible}, function(out)
				if out and out.shared then show_gossip(teller, listener, out, listeners) elseif then_cb then then_cb() end
			end)
		end
		ask(a, b, function() ask(b, a) end)
	end
end

local function try_meet(self, pos)
	for _, other in ipairs(npcasso.each_npc(pos, MEET_RANGE)) do
		if other ~= self and other.npc_id and (other.meet_until or 0) <= now() and not other.fleeing then
			local key = self.npc_id < other.npc_id and self.npc_id .. "|" .. other.npc_id or other.npc_id .. "|" .. self.npc_id
			if (pair_cooldown[key] or 0) <= now() then
				pair_cooldown[key] = now() + PAIR_COOLDOWN
				start_meeting(self, other)
				return true
			end
		end
	end
	return false
end

-- Walking -----------------------------------------------------------------------------------------

local function arrive(self, pos)
	halt(self)
	self.dest, self.path = nil, nil
	self.rest = math.random(5, 15)
	if vector.distance(pos, self.home) < 1.5 then self.object:set_yaw(self.post_yaw) end
end

local function walk(self, dt, pos)
	if not self.dest then
		self.rest = (self.rest or 0) - dt
		if self.rest > 0 then return end
		if is_day() and not self.errand then
			local places = village_places()
			self.dest = #places > 0 and vector.round(places[math.random(#places)]) or self.home
		elseif vector.distance(pos, self.home) > 2 then
			self.dest = self.home
		else
			self.rest = 20
			return
		end
		self.path, self.walk_t = nil, 0
	end
	if not self.path then
		local start = vector.round(pos)
		self.path = core.find_path(start, vector.round(self.dest), 40, 1, 3, "A*_noprediction") or {self.dest}
		self.wp = 1
	end
	local target = self.path[self.wp]
	local d = vector.subtract(target, pos)
	local flat = {x = d.x, y = 0, z = d.z}
	if vector.length(flat) < 0.6 then
		self.wp = self.wp + 1
		if self.wp > #self.path then arrive(self, pos) end
		return
	end
	self.walk_t = (self.walk_t or 0) + dt
	if self.walk_t > 40 then  -- lost: head home
		if vector.distance(self.dest, self.home) < 1 then return arrive(self, pos) end
		self.dest, self.path, self.walk_t = self.home, nil, 0
		return
	end
	local v = vector.multiply(vector.normalize(flat), WALK_SPEED)
	local vy = self.object:get_velocity().y
	if d.y > 0.4 and math.abs(vy) < 0.1 then vy = 5.5 end  -- step up a block
	self.object:set_velocity({x = v.x, y = vy, z = v.z})
	self.object:set_yaw(math.atan2(-flat.x, flat.z))
	set_walking(self, true)
end

local function flee(self, away, speed)
	self.dest, self.path, self.fleeing = nil, nil, true
	local v = vector.multiply(vector.normalize({x = away.x, y = 0, z = away.z}), speed)
	self.object:set_velocity({x = v.x, y = self.object:get_velocity().y, z = v.z})
	self.object:set_yaw(math.atan2(-v.x, v.z))
	set_walking(self, true)
end

-- Called from the NPC's on_step every 0.25 s.
function npcasso.life_step(self, dt, pos)
	if (self.meet_until or 0) > now() then return halt(self) end
	self.fleeing = false
	local player, pdist = nearest_player(pos)
	local mood = npcasso.moods[self.npc_id] or "neutral"
	if player then
		local ppos = player:get_pos()
		local away = vector.subtract(pos, ppos)
		if mood == "afraid" and pdist < 8 then return flee(self, away, FLEE_SPEED) end
		if mood == "hostile" and pdist < 4 then return flee(self, away, WALK_SPEED) end
		if mood == "wary" and pdist < 6 then halt(self); self.dest = nil; return face(self, ppos) end
		if mood == "friendly" and pdist < 14 and pdist > 3.5 and now() >= (self.next_visit or 0) then
			self.next_visit = now() + 300
			self.dest, self.path, self.walk_t = vector.round(ppos), {vector.round(ppos)}, 0
			self.wp = 1
		end
	end
	if self.errand then
		local w = npcasso.npc_entity(self.errand)
		if not w then
			self.errand = nil
		elseif vector.distance(w.object:get_pos(), pos) < MEET_RANGE then
			self.errand = nil  -- close enough; the meeting below passes the news on
		else
			local wp = vector.round(w.object:get_pos())
			self.dest, self.path, self.wp = wp, {wp}, 1
		end
	end
	self.meet_check = (self.meet_check or 0) + dt
	if self.meet_check >= 1 then
		self.meet_check = 0
		if try_meet(self, pos) then return end
	end
	walk(self, dt, pos)
end

-- Auto-talk: stop in front of a villager and face them for a moment -------------------------------

local autotalk_block, hold = {}, {}

function npcasso.on_talk_closed(name, npc_id)
	autotalk_block[name] = autotalk_block[name] or {}
	autotalk_block[name][npc_id] = now() + AUTOTALK_BLOCK
end

local talk_t = 0
core.register_globalstep(function(dtime)
	talk_t = talk_t + dtime
	if talk_t < 0.25 then return end
	local dt = talk_t
	talk_t = 0
	if not core.settings:get_bool("npcasso.auto_talk", true) then return end
	for _, p in ipairs(core.get_connected_players()) do
		local name = p:get_player_name()
		local found
		if not npcasso.talk[name] then
			local eye = vector.offset(p:get_pos(), 0, 1.5, 0)
			local look = p:get_look_dir()
			for _, e in ipairs(npcasso.each_npc(p:get_pos(), AUTOTALK_RANGE)) do
				local to = vector.normalize(vector.subtract(vector.offset(e.object:get_pos(), 0, 1.2, 0), eye))
				local mood = npcasso.moods[e.npc_id]
				local blocked = ((autotalk_block[name] or {})[e.npc_id] or 0) > now()
				if vector.dot(look, to) > AUTOTALK_COS and not blocked and mood ~= "hostile" and mood ~= "afraid" then
					found = e.npc_id
					break
				end
			end
		end
		if found and hold[name] and hold[name].npc == found then
			hold[name].t = hold[name].t + dt
			if hold[name].t >= AUTOTALK_HOLD then
				hold[name] = nil
				npcasso.open_talk(p, found)
			end
		else
			hold[name] = found and {npc = found, t = 0} or nil
		end
	end
end)

-- Monsters: kept out of the village; player kills count for XP and quests ------------------------

local safe_t = 0
core.register_globalstep(function(dtime)
	safe_t = safe_t + dtime
	if safe_t < 2 then return end
	safe_t = 0
	local o = npcasso.village()
	if not o then return end
	for _, obj in ipairs(core.get_objects_inside_radius(o, SAFE_RADIUS)) do
		local e = obj:get_luaentity()
		if e and e.name and e.name:find("^mobs_monster:") then obj:remove() end
	end
end)

core.register_on_mods_loaded(function()
	for name, def in pairs(core.registered_entities) do
		if name:find("^mobs_monster:") then
			local old = def.on_die
			def.on_die = function(self, pos)
				local cause = self.cause_of_death or {}
				local killer = cause.puncher
				if killer and killer.is_player and killer:is_player() then
					npcasso.event(killer, "slay", nil, {mob = name}, {})
				end
				if old then return old(self, pos) end
			end
		end
	end
end)

-- Harvests (ripe wheat) earn a little XP.
core.register_on_dignode(function(pos, oldnode, digger)
	if oldnode.name == "farming:wheat_8" and digger and digger:is_player() then
		npcasso.event(digger, "harvest", nil, {item = oldnode.name}, {})
	end
end)
