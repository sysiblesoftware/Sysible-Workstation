/* Sysible System Monitor — a compact CPU / MEM / DISK readout in the top-right
 * panel, styled in the Sysible palette (Option A: labelled percentages with
 * brand-coloured dots). Local-only: reads /proc and statfs, spawns nothing on
 * the tick path. Targets GNOME Shell 43/44 (Debian bookworm), legacy imports. */
const { St, GObject, GLib, Gio, Clutter } = imports.gi;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;

const REFRESH_SECONDS = 2;      // CPU + memory cadence
const DISK_EVERY_TICKS = 8;     // disk changes slowly → every ~16s
const WARN_PCT = 90;            // a metric at/above this turns red

// Sysible palette
const GREEN = '#6ddb73';
const BLUE  = '#5580ee';
const AMBER = '#f0c080';
const RED   = '#e07b76';

function readText(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        if (!ok || !bytes)
            return null;
        return new TextDecoder().decode(bytes);
    } catch (e) {
        return null;
    }
}

function fmtGiB(bytes) {
    return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GiB';
}

const SysibleMonitor = GObject.registerClass(
class SysibleMonitor extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Sysible System Monitor', false);

        this._box = new St.BoxLayout({ style_class: 'sysible-sysmon' });
        this.add_child(this._box);

        // key, label, brand colour
        this._metrics = [
            ['cpu',  'CPU',  GREEN],
            ['mem',  'MEM',  BLUE],
            ['disk', 'DISK', AMBER],
        ];
        this._w = {};
        for (const [key, label, color] of this._metrics) {
            const seg = new St.BoxLayout({ style_class: 'sysible-sysmon-seg' });
            const dot = new St.Label({ text: '●',
                style_class: 'sysible-sysmon-dot',
                y_align: Clutter.ActorAlign.CENTER });
            const lab = new St.Label({ text: label,
                style_class: 'sysible-sysmon-label',
                y_align: Clutter.ActorAlign.CENTER });
            const val = new St.Label({ text: '--%',
                style_class: 'sysible-sysmon-val',
                y_align: Clutter.ActorAlign.CENTER });
            seg.add_child(dot);
            seg.add_child(lab);
            seg.add_child(val);
            this._box.add_child(seg);
            this._w[key] = { dot, val, color };
        }

        // Drop-down breakdown.
        this._miCpu = new PopupMenu.PopupMenuItem('CPU: …', { reactive: false });
        this._miMem = new PopupMenu.PopupMenuItem('Memory: …', { reactive: false });
        this._miDisk = new PopupMenu.PopupMenuItem('Disk (/): …', { reactive: false });
        this.menu.addMenuItem(this._miCpu);
        this.menu.addMenuItem(this._miMem);
        this.menu.addMenuItem(this._miDisk);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const open = new PopupMenu.PopupMenuItem('Open System Monitor');
        open.connect('activate', () => this._launchSystemMonitor());
        this.menu.addMenuItem(open);

        this._diskFile = Gio.File.new_for_path('/');
        this._lastCpu = this._readCpuTotals();
        this._diskPct = null;
        this._diskUsed = 0;
        this._diskSize = 0;
        this._tickCount = 0;

        this._updateDisk();
        this._tick();
        this._timeout = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, REFRESH_SECONDS, () => {
                this._tick();
                return GLib.SOURCE_CONTINUE;
            });
    }

    // ---- readers ----------------------------------------------------------
    _readCpuTotals() {
        // First line of /proc/stat: "cpu  user nice system idle iowait irq …"
        const txt = readText('/proc/stat');
        if (!txt)
            return null;
        const line = txt.split('\n', 1)[0];
        const parts = line.trim().split(/\s+/).slice(1).map(Number);
        if (parts.length < 4 || parts.some(isNaN))
            return null;
        const idle = (parts[3] || 0) + (parts[4] || 0);  // idle + iowait
        const total = parts.reduce((a, b) => a + b, 0);
        return { idle, total };
    }

    _cpuPct() {
        const now = this._readCpuTotals();
        if (!now || !this._lastCpu) {
            this._lastCpu = now;
            return null;
        }
        const dTotal = now.total - this._lastCpu.total;
        const dIdle = now.idle - this._lastCpu.idle;
        this._lastCpu = now;
        if (dTotal <= 0)
            return null;
        return Math.max(0, Math.min(100, Math.round((1 - dIdle / dTotal) * 100)));
    }

    _mem() {
        const txt = readText('/proc/meminfo');
        if (!txt)
            return null;
        const get = (k) => {
            const m = txt.match(new RegExp('^' + k + ':\\s+(\\d+)', 'm'));
            return m ? parseInt(m[1], 10) * 1024 : null;   // kB → bytes
        };
        const total = get('MemTotal');
        let avail = get('MemAvailable');
        if (total === null)
            return null;
        if (avail === null) {   // very old kernels: approximate
            const free = get('MemFree') || 0;
            const cached = get('Cached') || 0;
            const buffers = get('Buffers') || 0;
            avail = free + cached + buffers;
        }
        const used = Math.max(0, total - avail);
        return { used, total, pct: Math.round((used / total) * 100) };
    }

    _updateDisk() {
        // statfs on / — async so a slow mount can't stall the shell.
        this._diskFile.query_filesystem_info_async(
            'filesystem::size,filesystem::used,filesystem::free',
            GLib.PRIORITY_DEFAULT, null, (file, res) => {
                try {
                    const info = file.query_filesystem_info_finish(res);
                    const size = info.get_attribute_uint64('filesystem::size');
                    let used = info.get_attribute_uint64('filesystem::used');
                    if (!used) {
                        const free = info.get_attribute_uint64('filesystem::free');
                        used = size - free;
                    }
                    if (size > 0) {
                        this._diskSize = size;
                        this._diskUsed = used;
                        this._diskPct = Math.round((used / size) * 100);
                    }
                } catch (e) {
                    // leave the last known value
                }
            });
    }

    // ---- render -----------------------------------------------------------
    _set(key, pct) {
        const w = this._w[key];
        if (pct === null || pct === undefined) {
            w.val.set_text('--%');
            return;
        }
        w.val.set_text(pct + '%');
        const warn = pct >= WARN_PCT;
        w.dot.set_style('color: ' + (warn ? RED : w.color) + ';');
        w.val.set_style(warn ? 'color: ' + RED + ';' : '');
    }

    _tick() {
        const cpu = this._cpuPct();
        this._set('cpu', cpu);

        const mem = this._mem();
        this._set('mem', mem ? mem.pct : null);

        if (this._tickCount % DISK_EVERY_TICKS === 0)
            this._updateDisk();
        this._tickCount++;
        this._set('disk', this._diskPct);

        // Menu breakdown (only matters while open, but cheap to keep fresh).
        if (this.menu.isOpen) {
            const load = (readText('/proc/loadavg') || '').split(' ').slice(0, 3).join(' ');
            this._miCpu.label.set_text('CPU: ' + (cpu === null ? '—' : cpu + '%')
                + (load ? '   load ' + load : ''));
            if (mem)
                this._miMem.label.set_text('Memory: ' + fmtGiB(mem.used)
                    + ' / ' + fmtGiB(mem.total) + '  (' + mem.pct + '%)');
            if (this._diskSize)
                this._miDisk.label.set_text('Disk (/): ' + fmtGiB(this._diskUsed)
                    + ' / ' + fmtGiB(this._diskSize) + '  (' + this._diskPct + '%)');
        }
        return GLib.SOURCE_CONTINUE;
    }

    _launchSystemMonitor() {
        const Shell = imports.gi.Shell;
        const app = Shell.AppSystem.get_default()
            .lookup_app('gnome-system-monitor.desktop');
        if (app)
            app.activate();
        else
            Main.notify('Sysible System Monitor',
                'gnome-system-monitor is not installed.');
    }

    destroy() {
        if (this._timeout) {
            GLib.source_remove(this._timeout);
            this._timeout = null;
        }
        super.destroy();
    }
});

let _indicator = null;

function init() {}

function enable() {
    _indicator = new SysibleMonitor();
    // Insert at the left end of the right box → just left of the system icons.
    Main.panel.addToStatusArea('sysible-sysmonitor', _indicator, 0, 'right');
}

function disable() {
    if (_indicator) {
        _indicator.destroy();
        _indicator = null;
    }
}
