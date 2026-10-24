import sys, glob
try:
    from lupa.luajit21 import LuaRuntime
    tag = "luajit21"
except Exception:
    from lupa.lua51 import LuaRuntime
    tag = "lua51"
lua = LuaRuntime()
bad = 0
for f in sorted(glob.glob("luanti/mods/npcasso/*.lua")):
    src = open(f, encoding="utf-8").read()
    fn, err = lua.eval("function(s, n) local f, e = loadstring(s, n); return f ~= nil, e or false end")(src, "@" + f)
    print(("OK   " if fn else "FAIL ") + f.split("\\")[-1], "" if fn else err)
    bad += 0 if fn else 1
print(tag, "bad:", bad)
