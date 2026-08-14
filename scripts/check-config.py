#!/usr/bin/env python3
"""Sysible Linux config regression sweep — validates every live-build input that
the package-build CI doesn't cover: shell hooks, dconf, gschema, .desktop files,
the GRUB theme, the hicolor icon set, Calamares config, systemd units, the
package list, and cross-references between them.

Run from anywhere:  python3 scripts/check-config.py
Exit 0 = pass, 1 = one or more failures. Checks needing PIL/PyYAML/xmllint are
skipped (reported) when those tools are absent, so it never hard-fails on a bare
box; CI installs them so every check actually runs."""
import os, re, subprocess, glob, sys, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
LB = ROOT/"live-build"/"config"
CHROOT = LB/"includes.chroot"
HAVE_XMLLINT = shutil.which("xmllint") is not None
try:
    from PIL import Image; HAVE_PIL=True
except Exception: HAVE_PIL=False
try:
    import yaml; HAVE_YAML=True
except Exception: HAVE_YAML=False
FAILS=[]; WARNS=[]; OKS=[]
def ok(c,m): OKS.append((c,m))
def warn(c,m): WARNS.append((c,m))
def fail(c,m): FAILS.append((c,m))

def sh_syntax(path):
    r=subprocess.run(["bash","-n",str(path)],capture_output=True,text=True)
    return r.returncode==0, r.stderr.strip()

# 1) SHELL SYNTAX + exec bits ------------------------------------------------
shell_files=[]
for pat in ["config/hooks/**/*.hook.*","build.sh"]:
    shell_files+=[Path(p) for p in glob.glob(str(ROOT/"live-build"/pat),recursive=True)]
shell_files+=[Path(p) for p in glob.glob(str(ROOT/"scripts"/"*.sh"))]
# any shell scripts shipped into the image
for p in glob.glob(str(CHROOT/"**"/"*"),recursive=True):
    pp=Path(p)
    if pp.is_file():
        try:
            head=pp.open('rb').read(80)
        except Exception: continue
        if head.startswith(b"#!") and (b"/sh" in head.split(b"\n")[0] or b"/bash" in head.split(b"\n")[0]):
            shell_files.append(pp)
shell_files=sorted(set(shell_files))
for f in shell_files:
    good,err=sh_syntax(f)
    if good: ok("shell",f.relative_to(ROOT))
    else: fail("shell",f"{f.relative_to(ROOT)}: {err}")
    # hooks must be executable
    if ".hook." in f.name and not os.access(f,os.X_OK):
        fail("hook-exec",f"{f.relative_to(ROOT)} is not executable (live-build will skip it)")

# 2) DESKTOP FILES -----------------------------------------------------------
desk=[Path(p) for p in glob.glob(str(CHROOT/"**"/"*.desktop"),recursive=True)]
for d in desk:
    txt=d.read_text(errors="replace")
    rel=d.relative_to(ROOT)
    if "[Desktop Entry]" not in txt: fail("desktop",f"{rel}: no [Desktop Entry]"); continue
    kv=dict(re.findall(r'^([A-Za-z0-9-]+)\s*=\s*(.*)$',txt,re.M))
    for req in ("Type","Name"):
        if req not in kv: fail("desktop",f"{rel}: missing {req}")
    if kv.get("Type")=="Application" and "Exec" not in kv:
        fail("desktop",f"{rel}: Application without Exec")
    ok("desktop",rel)
    # Icon= (a name, not a path) should resolve to a shipped icon. Sysible-owned
    # icons must be in includes.chroot; stock icon names are provided by themes.
    icon=kv.get("Icon","").strip()
    if icon and "/" not in icon and icon.startswith("sysible"):
        found=glob.glob(str(CHROOT/f"usr/share/icons/hicolor/*/apps/{icon}.*")) \
            + glob.glob(str(CHROOT/f"usr/share/pixmaps/{icon}.*"))
        if found: ok("desktop-icon",f"{rel}: Icon={icon} resolves")
        else: fail("desktop-icon",f"{rel}: Icon={icon} not shipped in includes.chroot")

# 3) GSCHEMA OVERRIDES (keyfile well-formedness) -----------------------------
for g in glob.glob(str(CHROOT/"usr/share/glib-2.0/schemas"/"*.gschema.override")):
    gp=Path(g); rel=gp.relative_to(ROOT)
    txt=gp.read_text()
    if not re.search(r'^\[.+\]',txt,re.M): fail("gschema",f"{rel}: no [schema] header")
    else: ok("gschema",rel)

# 4) DCONF KEYFILES (INI + light GVariant sanity) ----------------------------
def gvariant_ok(v):
    v=v.strip()
    if v in ("true","false"): return True
    if re.fullmatch(r'-?\d+',v): return True
    if re.fullmatch(r'-?\d+\.\d+',v): return True
    if re.fullmatch(r"'(?:[^'\\]|\\.)*'",v): return True         # string
    if v.startswith("[") and v.endswith("]"):                    # array
        inner=v[1:-1].strip()
        if inner=="": return True
        parts=re.findall(r"'(?:[^'\\]|\\.)*'",inner)
        return len(parts)>=1 or all(re.fullmatch(r'-?\d+',x.strip()) for x in inner.split(','))
    if v.startswith("@"): return True
    if v.startswith("(") and v.endswith(")"): return True
    return False
for db in glob.glob(str(CHROOT/"etc/dconf/db"/"**"),recursive=True):
    dp=Path(db)
    if dp.is_file() and dp.parent.name.endswith(".d"):
        rel=dp.relative_to(ROOT); sec=None; bad=False
        for i,line in enumerate(dp.read_text().splitlines(),1):
            s=line.strip()
            if not s or s.startswith("#"): continue
            if s.startswith("[") and s.endswith("]"): sec=s; continue
            if "=" not in s: fail("dconf",f"{rel}:{i}: not key=value: {s}"); bad=True; continue
            k,v=s.split("=",1)
            if not gvariant_ok(v): fail("dconf",f"{rel}:{i}: unparseable value: {v}"); bad=True
        if not bad: ok("dconf",rel)

# 5) GRUB THEME --------------------------------------------------------------
theme=CHROOT/"boot/grub/themes/sysible/theme.txt"
if theme.exists():
    t=theme.read_text(); tdir=theme.parent
    refs=set(re.findall(r'(?:desktop-image|file)\s*[:=]\s*"([^"]+)"',t))
    pm=re.search(r'selected_item_pixmap_style\s*=\s*"([^"]+)"',t)
    if pm:
        for suf in ("c","n","s","e","w","nw","ne","sw","se"):
            refs.add(pm.group(1).replace("*",suf))   # selbar_*.png -> selbar_c.png ...
    for r in refs:
        if not (tdir/r).exists(): fail("grub",f"theme.txt references missing {r}")
        else: ok("grub",f"pixmap {r}")
    # geometry sanity: item_spacing must exceed 2*item_padding (the bug we fixed)
    ih=int((re.search(r'item_height\s*=\s*(\d+)',t) or [0,0])[1])
    ip=int((re.search(r'item_padding\s*=\s*(\d+)',t) or [0,0])[1])
    isp=int((re.search(r'item_spacing\s*=\s*(\d+)',t) or [0,0])[1])
    if isp>2*ip: ok("grub",f"pill geometry safe (spacing {isp} > 2*padding {2*ip})")
    else: fail("grub",f"pill may overlap: item_spacing {isp} <= 2*item_padding {2*ip}")
else:
    fail("grub","theme.txt missing")

# 6) ICONS: PNG dims match dir, SVGs parse, ladders complete -----------------
hicolor=CHROOT/"usr/share/icons/hicolor"
if hicolor.exists():
    if HAVE_PIL:
        for png in glob.glob(str(hicolor/"*/apps/*.png")):
            pp=Path(png); rel=pp.relative_to(ROOT)
            dim=pp.parent.parent.name  # e.g. 64x64
            m=re.match(r'(\d+)x(\d+)',dim)
            try:
                im=Image.open(pp); w,h=im.size
            except Exception as e:
                fail("icon",f"{rel}: unreadable ({e})"); continue
            if m and (w,h)!=(int(m[1]),int(m[2])):
                fail("icon",f"{rel}: {w}x{h} in {dim} dir")
            else: ok("icon",rel)
    else: warn("icon","PIL absent — skipped PNG dimension checks")
    if HAVE_XMLLINT:
        for svg in glob.glob(str(hicolor/"scalable/apps/*.svg")):
            r=subprocess.run(["xmllint","--noout",svg],capture_output=True,text=True)
            if r.returncode==0: ok("icon",Path(svg).relative_to(ROOT))
            else: fail("icon",f"{Path(svg).relative_to(ROOT)}: {r.stderr.strip()}")
    else: warn("icon","xmllint absent — skipped SVG parse checks")
    # ladder completeness for the two dock icons
    for name in ("sysible-install","io.systerm.SysTerm"):
        have={Path(p).parent.parent.name for p in glob.glob(str(hicolor/f"*/apps/{name}.png"))}
        need={f"{s}x{s}" for s in (16,24,32,48,64,128,256)}
        missing=need-have
        if missing: warn("icon",f"{name}: missing sizes {sorted(missing)}")
        else: ok("icon",f"{name}: full size ladder")

# 7) CALAMARES YAML/conf -----------------------------------------------------
cal=CHROOT/"etc/calamares"
if cal.exists() and HAVE_YAML:
    for y in glob.glob(str(cal/"**"/"*"),recursive=True):
        yp=Path(y)
        if yp.is_file() and yp.suffix in (".conf",".yaml",".yml",".desc"):
            try:
                yaml.safe_load(yp.read_text()); ok("calamares",yp.relative_to(ROOT))
            except Exception as e:
                fail("calamares",f"{yp.relative_to(ROOT)}: {str(e).splitlines()[0]}")
elif cal.exists(): warn("calamares","PyYAML absent — skipped Calamares config parse")

# 8) SYSTEMD UNITS -----------------------------------------------------------
for u in glob.glob(str(CHROOT/"**"/"*.service"),recursive=True)+glob.glob(str(CHROOT/"**"/"*.timer"),recursive=True):
    up=Path(u); rel=up.relative_to(ROOT)
    if up.is_symlink():
        # enablement symlink (e.g. *.target.wants/foo.service). Resolve against
        # the chroot; a target provided by an installed package won't exist in
        # the source tree, so only flag when the unit is a Sysible-shipped one.
        tgt=os.readlink(up); base=os.path.basename(tgt)
        shipped_unit=list(glob.glob(str(CHROOT/"**"/base),recursive=True))
        real=[p for p in shipped_unit if not Path(p).is_symlink()]
        if real: ok("systemd",f"{rel} -> {base} (shipped)")
        else: warn("systemd",f"{rel}: enables {base}, not shipped in tree (must be package-provided)")
        continue
    try: txt=up.read_text()
    except Exception as e: fail("systemd",f"{rel}: unreadable ({e})"); continue
    if "[Unit]" not in txt: fail("systemd",f"{rel}: no [Unit]")
    elif up.suffix==".service" and "ExecStart=" not in txt and "Type=oneshot" not in txt:
        warn("systemd",f"{rel}: service without ExecStart")
    else: ok("systemd",rel)

# 9) XML well-formedness (plymouth themes etc.) ------------------------------
if HAVE_XMLLINT:
    for x in glob.glob(str(CHROOT/"**"/"*.xml"),recursive=True):
        r=subprocess.run(["xmllint","--noout",x],capture_output=True,text=True)
        if r.returncode==0: ok("xml",Path(x).relative_to(ROOT))
        else: fail("xml",f"{Path(x).relative_to(ROOT)}: {r.stderr.strip()}")
else: warn("xml","xmllint absent — skipped XML well-formedness checks")

# 10) PACKAGE LIST -----------------------------------------------------------
pl=LB/"package-lists"/"sysible.list.chroot"
if pl.exists():
    pkgs=[l.strip() for l in pl.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
    dupes={p for p in pkgs if pkgs.count(p)>1}
    if dupes: warn("packages",f"duplicate entries: {sorted(dupes)}")
    bad=[p for p in pkgs if not re.fullmatch(r'[a-z0-9][a-z0-9.+-]+',p)]
    if bad: fail("packages",f"malformed package names: {bad}")
    ok("packages",f"{len(pkgs)} packages, {len(set(pkgs))} unique")

# 11) CROSS-REF: dconf favorite-apps -> shipped .desktop ---------------------
shipped={Path(p).name for p in glob.glob(str(CHROOT/"usr/share/applications/*.desktop"))}
# Provided by installed .debs rather than includes.chroot: systerm.desktop ships
# in the SysTerm package (built + included by build.sh); the rest are stock GNOME.
SYSTEM_KNOWN={"org.gnome.Nautilus.desktop","firefox-esr.desktop",
              "org.gnome.TextEditor.desktop","codium.desktop","systerm.desktop",
              "com.giuspen.cherrytree.desktop","cherrytree.desktop"}
for db in glob.glob(str(CHROOT/"etc/dconf/db"/"**"),recursive=True):
    dp=Path(db)
    if dp.is_file():
        m=re.search(r"favorite-apps=\[(.*?)\]",dp.read_text())
        if m:
            for app in re.findall(r"'([^']+)'",m.group(1)):
                if app in shipped or app in SYSTEM_KNOWN: ok("favorites",f"{app} resolvable")
                else: warn("favorites",f"{app}: not shipped in includes.chroot and not a known system app")

# ---- REPORT ----------------------------------------------------------------
print("="*72)
cats={}
for c,_ in OKS: cats.setdefault(c,[0,0,0])[0]+=1
for c,_ in WARNS: cats.setdefault(c,[0,0,0])[1]+=1
for c,_ in FAILS: cats.setdefault(c,[0,0,0])[2]+=1
print(f"{'CATEGORY':<14}{'OK':>6}{'WARN':>6}{'FAIL':>6}")
for c in sorted(cats): o,w,f=cats[c]; print(f"{c:<14}{o:>6}{w:>6}{f:>6}")
print("-"*72)
if WARNS:
    print("\nWARNINGS:")
    for c,m in WARNS: print(f"  [{c}] {m}")
if FAILS:
    print("\nFAILURES:")
    for c,m in FAILS: print(f"  [{c}] {m}")
print("\n"+("RESULT: FAIL — %d failure(s)"%len(FAILS) if FAILS else "RESULT: PASS"))
sys.exit(1 if FAILS else 0)
