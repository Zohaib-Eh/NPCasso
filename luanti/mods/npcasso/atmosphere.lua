-- The village slides into winter a little at a time. Sky, fog, colour, snow, wind, music and voices all
-- follow one number per player: 0 on arrival, 1 on day 10. The backend says where it is on each tick and
-- this file eases toward it, so the change happens in front of your eyes and never in a jump.

local target, shown, wind, flurry, dressed = {}, {}, {}, {}, {}

local function mix(a, b, t) return a + (b - a) * t end
local function rgb(a, b, t)
	return {r = math.floor(mix(a[1], b[1], t)), g = math.floor(mix(a[2], b[2], t)), b = math.floor(mix(a[3], b[3], t))}
end

function npcasso.winter_of(name) return shown[name] or 0 end
function npcasso.winter_now()
	local best = 0
	for name in pairs(shown) do best = math.max(best, shown[name]) end
	return best
end

function npcasso.set_winter(name, w)
	target[name] = w
	if not shown[name] then shown[name] = w end
end

local function dress_sky(player, w)
	player:set_sky({
		type = "regular", clouds = true,
		sky_color = {
			day_sky = rgb({97, 181, 245}, {118, 126, 138}, w), day_horizon = rgb({144, 211, 254}, {168, 170, 172}, w),
			dawn_sky = rgb({180, 186, 250}, {120, 118, 128}, w), dawn_horizon = rgb({186, 193, 240}, {150, 146, 150}, w),
			night_sky = rgb({0, 107, 255}, {10, 16, 34}, w), night_horizon = rgb({64, 144, 255}, {30, 38, 58}, w),
		},
		fog = w < 0.03 and {fog_distance = -1, fog_start = -1} or
			{fog_distance = math.floor(mix(190, 70, w)), fog_start = mix(0.5, 0.1, w)},
	})
	player:set_clouds({density = mix(0.4, 0.8, w), color = w < 0.03 and "#fff0f0e5" or
		string.format("#%02x%02x%02xe8", math.floor(mix(240, 150, w)), math.floor(mix(240, 156, w)),
			math.floor(mix(245, 166, w))),
		thickness = mix(16, 28, w), speed = {x = mix(-2, -6, w), z = 0}})
	player:set_lighting({saturation = mix(1, 0.5, w)})
end

-- Snow drifts down around the player once it is cold enough, thicker as winter closes. None indoors.
local function snow(player, w)
	if w < 0.2 then return end
	local head = vector.offset(player:get_pos(), 0, 1.6, 0)
	if not core.line_of_sight(head, vector.offset(head, 0, 12, 0)) then return end
	local k = (w - 0.2) / 0.8
	core.add_particlespawner({
		amount = math.floor(10 + 70 * k), time = 4, attached = player,
		minpos = {x = -14, y = 8, z = -14}, maxpos = {x = 14, y = 10, z = 14},
		minvel = {x = -0.8 - k, y = -1.4, z = -0.4}, maxvel = {x = -0.2, y = -2.4, z = 0.4},
		minexptime = 4, maxexptime = 6, minsize = 0.6, maxsize = 1.3 + k,
		texture = "npcasso_flake.png", playername = player:get_player_name(),
	})
end

local function bed_of_wind(player, w)
	local name = player:get_player_name()
	local gain = w < 0.08 and 0 or 0.04 + 0.5 * w ^ 1.3
	if not wind[name] and gain > 0 then
		wind[name] = core.sound_play("npcasso_wind", {to_player = name, loop = true, gain = 0.01})
	end
	if wind[name] then core.sound_fade(wind[name], 0.1, gain) end
end

local tick_t = 0
core.register_globalstep(function(dtime)
	tick_t = tick_t + dtime
	if tick_t < 1 then return end
	local dt = tick_t
	tick_t = 0
	for _, player in ipairs(core.get_connected_players()) do
		local name = player:get_player_name()
		local goal = target[name]
		if goal then
			shown[name] = mix(shown[name], goal, math.min(1, dt * 0.2))
			dressed[name] = (dressed[name] or {w = -1, at = 0})
			if math.abs(shown[name] - dressed[name].w) > 0.004 or dressed[name].at >= 10 then
				dress_sky(player, shown[name])  -- again every 10 s: another mod may have touched the sky
				bed_of_wind(player, shown[name])
				dressed[name] = {w = shown[name], at = 0}
			end
			dressed[name].at = dressed[name].at + dt
			flurry[name] = (flurry[name] or 0) + dt
			if flurry[name] >= 3.5 then
				flurry[name] = 0
				snow(player, shown[name])
			end
		end
	end
end)

core.register_on_leaveplayer(function(player)
	local name = player:get_player_name()
	if wind[name] then core.sound_stop(wind[name]) end
	target[name], shown[name], wind[name], flurry[name], dressed[name] = nil, nil, nil, nil, nil
end)
