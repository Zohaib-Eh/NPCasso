-- Demo view of the hidden dimensions: /npcasso stats. Real play never shows these scores.
-- A formspec has no polygon primitive, so the chart is rasterised on a small grid and drawn as
-- run-length boxes. Centre is -1, the middle ring is 0, the rim is +1.

local N, CELL = 72, 0.1                 -- grid cells per side, formspec units per cell
local R = 33                            -- cells from centre to the +1 rim
local MID = N / 2
local OX, OY = 3.4, 1.5                 -- chart top-left in the formspec
local FX, FY = OX + MID * CELL, OY + MID * CELL
local TAU = math.pi * 2

local function mark(grid, x, y)
	local xi, yi = math.floor(x), math.floor(y)
	if xi < 0 or yi < 0 or xi >= N or yi >= N then return end
	grid[yi] = grid[yi] or {}
	grid[yi][xi] = true
end

local function line(grid, x1, y1, x2, y2)
	local steps = math.max(1, math.ceil(math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2) * 2))
	for s = 0, steps do
		local t = s / steps
		mark(grid, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
	end
end

local function ring(grid, r)
	local steps = math.ceil(TAU * r * 2)
	for s = 0, steps do
		local a = TAU * s / steps
		mark(grid, MID + r * math.cos(a), MID + r * math.sin(a))
	end
end

local function dot(grid, x, y)
	for dy = -1, 1 do for dx = -1, 1 do mark(grid, x + dx, y + dy) end end
end

local function inside(pts, x, y)
	local hit, j = false, #pts
	for i = 1, #pts do
		local a, b = pts[i], pts[j]
		if (a.y > y) ~= (b.y > y) and x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x then hit = not hit end
		j = i
	end
	return hit
end

local function boxes(out, grid, color)
	for y = 0, N - 1 do
		local row, x = grid[y], 0
		while row and x < N do
			if row[x] then
				local s = x
				while x + 1 < N and row[x + 1] do x = x + 1 end
				out[#out + 1] = ("box[%.3f,%.3f;%.3f,%.3f;%s]"):format(
					OX + s * CELL, OY + y * CELL, (x - s + 1) * CELL + 0.01, CELL + 0.01, color)
			end
			x = x + 1
		end
	end
end

local function tint(v)
	if v > 0.15 then return "#8fe08f" elseif v < -0.15 then return "#f0a070" end
	return "#d0d0d0"
end

function npcasso.radar_formspec(dims, opts)
	opts = opts or {}
	local count = #dims
	local faint, zero, fill, edge, tips = {}, {}, {}, {}, {}
	local pts, labels, seen = {}, {}, 0
	ring(faint, R)
	ring(zero, R / 2)
	for i, d in ipairs(dims) do
		local a = -math.pi / 2 + (i - 1) * TAU / count
		line(faint, MID, MID, MID + R * math.cos(a), MID + R * math.sin(a))
		local rad = R * ((d.value or 0) + 1) / 2
		pts[i] = {x = MID + rad * math.cos(a), y = MID + rad * math.sin(a)}
		seen = seen + (d.n or 0)
		local text = ("%s %+.2f"):format(d.dimension, d.value or 0)
		local w = #text * 0.105
		local c = math.cos(a)
		local lx = FX + (R * CELL + 0.3) * c
		local ly = FY + (R * CELL + 0.3) * math.sin(a)
		if c > 0.3 then elseif c < -0.3 then lx = lx - w else lx = lx - w / 2 end
		labels[#labels + 1] = ("label[%.2f,%.2f;%s]"):format(lx, ly,
			core.formspec_escape(core.colorize(tint(d.value or 0), text)))
	end
	for y = 0, N - 1 do
		for x = 0, N - 1 do
			if inside(pts, x + 0.5, y + 0.5) then fill[y] = fill[y] or {}; fill[y][x] = true end
		end
	end
	for i = 1, count do
		local a, b = pts[i], pts[i % count + 1]
		line(edge, a.x, a.y, b.x, b.y)
		dot(tips, a.x, a.y)
	end
	local out = {
		"formspec_version[6]size[14,11]bgcolor[#0d1016f0;true]" .. (opts.tabs or ""),
		"label[0.5,0.5;" .. core.formspec_escape(core.colorize("#ffd479", "Character profile")
			.. (opts.standing and ("   Standing: " .. opts.standing) or "  (demo view)")) .. "]",
		("box[%.2f,%.2f;%.2f,%.2f;#161c26ff]"):format(OX, OY, N * CELL, N * CELL),
	}
	boxes(out, faint, "#ffffff30")
	boxes(out, zero, "#ffffff66")
	boxes(out, fill, "#e8a03a55")
	boxes(out, edge, "#ffcf5aff")
	boxes(out, tips, "#ffffffff")
	for _, l in ipairs(labels) do out[#out + 1] = l end
	out[#out + 1] = ("label[0.5,9.3;%s]"):format(core.formspec_escape(
		("Centre -1, middle ring 0, rim +1. %d reading%s so far. Each point averages what villagers read from your acts."):format(
			seen, seen == 1 and "" or "s")))
	if not opts.tabs then out[#out + 1] = "button[11.6,9.1;2,0.7;refresh;Refresh]" end
	return table.concat(out)
end

-- `tabs` is set when this is the journal's Character tab; /npcasso stats shows it on its own.
function npcasso.show_radar(name, tabs)
	npcasso.get(("/profile?world=%s&player=%s"):format(npcasso.world(), name), function(s)
		if not s or not s.dimensions then
			return core.chat_send_player(name, "Backend unreachable.")
		end
		core.show_formspec(name, tabs and "npcasso:journal" or "npcasso:radar",
			npcasso.radar_formspec(s.dimensions, {tabs = tabs, standing = tabs and s.standing or nil}))
	end)
end

local DOT = {angry = "#FF6B5E", afraid = "#E8E0A0", hurt = "#9FB4D8", cold = "#A8A8A8",
	guarded = "#FFC24A", warm = "#9AE07A", fond = "#7AE0A8", neutral = "#D0D0D0"}

-- The journal's People tab: only villagers you have spoken to, with how that last meeting left them.
-- It is the mood from then, never live, so off-screen feelings stay off-screen.
function npcasso.show_people(name, tabs)
	npcasso.get(("/profile?world=%s&player=%s"):format(npcasso.world(), name), function(s)
		if not s or not s.met then return core.chat_send_player(name, "Backend unreachable.") end
		local fs = {"formspec_version[6]size[14,11]bgcolor[#0d1016f0;true]", tabs,
			"label[0.5,0.7;", core.formspec_escape(core.colorize("#ffd479", "People you have met")), "]"}
		for i, m in ipairs(s.met) do
			local y = 1.3 + (i - 1) * 0.7
			table.insert(fs, ("box[0.5,%.2f;0.3,0.3;%s]"):format(y + 0.1, DOT[m.mood] or "#D0D0D0"))
			table.insert(fs, ("label[1.1,%.2f;%s]"):format(y + 0.25, core.formspec_escape(
				("%s, %s: %s"):format(m.name, m.role, m.mood))))
		end
		if #s.met == 0 then table.insert(fs, "label[0.5,1.5;Nobody yet.]") end
		core.show_formspec(name, "npcasso:journal", table.concat(fs))
	end)
end

core.register_on_player_receive_fields(function(player, formname, fields)
	if formname == "npcasso:radar" and fields.refresh then
		npcasso.show_radar(player:get_player_name())
		return true
	end
end)
