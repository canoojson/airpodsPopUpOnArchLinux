// Indicador de AirPods para GNOME Shell (45 o posterior) sobre la API D-Bus de airpodsd:
// batería de cada auricular y de la caja, modo de escucha, detección de conversación y
// botón para conectarlos. Todo el trabajo lo hace airpodsd; aquí solo se muestra.

import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const BUS_NAME = 'io.github.AirpodsLinux';
const OBJ_PATH = '/io/github/AirpodsLinux';
const IFACE_XML = `
<node>
  <interface name="io.github.AirpodsLinux1">
    <method name="GetState"><arg type="s" direction="out"/></method>
    <method name="SetSetting"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="StateChanged"><arg type="s"/></signal>
  </interface>
</node>`;
const AirpodsProxy = Gio.DBusProxy.makeProxyWrapper(IFACE_XML);

const LOW_BATTERY = 20;

// Textos en castellano; con cualquier otro idioma, en inglés (como airpodsctl).
const EN = {
    'Desactivado': 'Off',
    'Sonido ambiente': 'Transparency',
    'Adaptativo': 'Adaptive',
    'Cancelación de ruido': 'Noise Cancellation',
    'Izquierdo': 'Left',
    'Derecho': 'Right',
    'Caja': 'Case',
    'Conectar a este equipo': 'Connect to this computer',
    'Modo de escucha': 'Listening mode',
    'Detección de conversación': 'Conversation Awareness',
    'Conectados': 'Connected',
    'No conectados': 'Not connected',
    'No emparejados': 'Not paired',
    'No se pudo conectar': 'Could not connect',
};
const SPANISH = GLib.get_language_names()[0].toLowerCase().startsWith('es');
const _ = text => (SPANISH ? text : EN[text] ?? text);

const MODE_LABELS = {
    off: _('Desactivado'),
    transparency: _('Sonido ambiente'),
    adaptive: _('Adaptativo'),
    noise: _('Cancelación de ruido'),
};

function field(state, name) {
    const f = state?.fields?.[name];
    return f ? f.value : null;
}

function batteryText(b) {
    if (!b)
        return '--';
    return `${b.level} %${b.charging ? ' ⚡' : ''}`;
}

function lowestPod(state) {
    const levels = ['left', 'right'].map(s => field(state, s)).filter(b => b).map(b => b.level);
    return levels.length ? Math.min(...levels) : null;
}

const AirpodsIndicator = GObject.registerClass(
class AirpodsIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.5, 'AirPods');
        this._state = null;

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({icon_name: 'audio-headphones-symbolic', style_class: 'system-status-icon'});
        this._label = new St.Label({text: '', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this._title = new PopupMenu.PopupMenuItem('AirPods', {reactive: false});
        this._title.label.style = 'font-weight: bold;';
        this.menu.addMenuItem(this._title);
        this._rows = {};
        for (const [key, name] of [['left', _('Izquierdo')], ['right', _('Derecho')], ['case', _('Caja')]]) {
            const item = new PopupMenu.PopupMenuItem(name, {reactive: false});
            const value = new St.Label({text: '--', x_expand: true, x_align: Clutter.ActorAlign.END});
            item.add_child(value);
            this._rows[key] = value;
            this.menu.addMenuItem(item);
        }

        this._connectItem = new PopupMenu.PopupMenuItem(_('Conectar a este equipo'));
        this._connectItem.connect('activate', () => this._connect());
        this.menu.addMenuItem(this._connectItem);

        this._modesSection = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem(_('Modo de escucha')));
        this.menu.addMenuItem(this._modesSection);
        this._modeItems = {};

        this._conversation = new PopupMenu.PopupSwitchMenuItem(_('Detección de conversación'), false);
        this._conversation.connect('toggled', (_item, on) =>
            this._setSetting('conversational_awareness', on ? 'on' : 'off'));
        this.menu.addMenuItem(this._conversation);

        this._proxy = null;
        this._signalId = 0;
        this._ownerId = 0;
        new AirpodsProxy(Gio.DBus.session, BUS_NAME, OBJ_PATH, (proxy, error) => {
            if (error) {
                console.warn(`AirPods Linux: ${error.message}`);
                return;
            }
            this._proxy = proxy;
            this._signalId = proxy.connectSignal('StateChanged', (_p, _sender, [json]) => this._update(json));
            this._ownerId = proxy.connect('notify::g-name-owner', () => this._refresh());
            this._refresh();
        }, null, Gio.DBusProxyFlags.DO_NOT_AUTO_START);
    }

    _refresh() {
        if (!this._proxy?.g_name_owner) {
            this._update(null);
            return;
        }
        this._proxy.GetStateRemote((result, error) => this._update(error ? null : result[0]));
    }

    _update(json) {
        try {
            this._state = json ? JSON.parse(json) : null;
        } catch {
            this._state = null;
        }
        const st = this._state;
        const lowest = lowestPod(st);
        // Sin airpodsd o sin datos todavía, el indicador no ocupa sitio en la barra.
        this.visible = st !== null && (lowest !== null || field(st, 'case') !== null);
        if (!this.visible)
            return;

        this._label.text = lowest !== null ? ` ${lowest} %` : '';
        this._label.style = lowest !== null && lowest <= LOW_BATTERY ? 'color: #ff3b30;' : '';
        const conn = _(st.connected === true ? 'Conectados' : st.connected === false ? 'No conectados' : 'No emparejados');
        this._title.label.text = `${st.name || st.model_name || 'AirPods'} · ${conn}`;
        for (const key of ['left', 'right', 'case'])
            this._rows[key].text = batteryText(field(st, key));
        this._connectItem.visible = st.connected === false && Boolean(st.address);

        const aap = st.aap || {};
        const own = aap.owner === 'airpodsd' && aap.connected;
        const modes = own ? aap.modes || [] : [];
        const current = aap.settings?.listening_mode;
        this._modesSection.removeAll();
        for (const mode of modes) {
            const item = new PopupMenu.PopupMenuItem(MODE_LABELS[mode] || mode);
            item.setOrnament(mode === current ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
            item.connect('activate', () => this._setSetting('listening_mode', mode));
            this._modesSection.addMenuItem(item);
        }
        const ca = aap.settings?.conversational_awareness;
        this._conversation.visible = own && ca !== undefined && ca !== null;
        this._conversation.setToggleState(ca === true && !aap.in_call);
        this._conversation.setSensitive(!aap.in_call);
    }

    _setSetting(name, value) {
        this._proxy?.SetSettingRemote(name, value, (_result, error) => {
            if (error)
                Main.notifyError('AirPods', error.message);
        });
    }

    _connect() {
        const address = this._state?.address;
        if (!address)
            return;
        try {
            const proc = Gio.Subprocess.new(['bluetoothctl', 'connect', address], Gio.SubprocessFlags.STDOUT_SILENCE);
            proc.wait_check_async(null, (p, res) => {
                try {
                    p.wait_check_finish(res);
                } catch {
                    Main.notifyError('AirPods', _('No se pudo conectar'));
                }
            });
        } catch (e) {
            Main.notifyError('AirPods', e.message);
        }
    }

    destroy() {
        if (this._proxy) {
            if (this._signalId)
                this._proxy.disconnectSignal(this._signalId);
            if (this._ownerId)
                this._proxy.disconnect(this._ownerId);
            this._proxy = null;
        }
        super.destroy();
    }
});

export default class AirpodsLinuxExtension extends Extension {
    enable() {
        this._indicator = new AirpodsIndicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
