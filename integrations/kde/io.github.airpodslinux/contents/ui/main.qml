// Plasmoide de AirPods para KDE Plasma 6: batería de cada auricular y de la caja, modo de
// escucha y botón para conectarlos. Lee el estado que publica airpodsd en
// $XDG_RUNTIME_DIR/airpods-linux/status.json y actúa con airpodsctl (ruta absoluta del
// propio estado, para no depender del PATH de la sesión).
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    readonly property string readCmd: "cat \"${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/airpods-linux/status.json\""
    readonly property int lowBattery: 20
    // Textos en castellano; con cualquier otro idioma, en inglés (como airpodsctl).
    readonly property bool spanish: Qt.locale().name.startsWith("es")
    readonly property var en: ({
        "Desactivado": "Off", "Sonido ambiente": "Transparency", "Adaptativo": "Adaptive",
        "Cancelación de ruido": "Noise Cancellation", "Izquierdo": "Left", "Derecho": "Right", "Caja": "Case",
        "airpodsd no está en ejecución": "airpodsd is not running",
        "Conectados a este equipo": "Connected to this computer", "No conectados": "Not connected",
        "No emparejados con este equipo": "Not paired with this computer",
        "Conectar a este equipo": "Connect to this computer", "Modo de escucha": "Listening mode",
        "Detección de conversación": "Conversation Awareness"
    })
    readonly property var modeLabels: ({
        "off": tr("Desactivado"),
        "transparency": tr("Sonido ambiente"),
        "adaptive": tr("Adaptativo"),
        "noise": tr("Cancelación de ruido")
    })
    property var st: null
    property bool busy: false

    function tr(text) {
        return spanish ? text : (en[text] || text)
    }
    function field(name) {
        return (st && st.fields && st.fields[name]) ? st.fields[name].value : null
    }
    function batteryText(b) {
        return b ? (b.level + " %" + (b.charging ? " ⚡" : "")) : "--"
    }
    function lowestPod() {
        const levels = ["left", "right"].map(field).filter(b => b !== null).map(b => b.level)
        return levels.length ? Math.min.apply(null, levels) : -1
    }
    function ownAap() {
        return st && st.aap && st.aap.owner === "airpodsd" && st.aap.connected
    }
    function shellQuote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'"
    }
    function ctl(args) {
        const bin = (st && st.ctl) ? st.ctl : "airpodsctl"
        busy = true
        executable.connectSource([bin].concat(args).map(shellQuote).join(" "))
    }

    P5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source)
            if (source === root.readCmd) {
                try {
                    root.st = data["exit code"] === 0 ? JSON.parse(data.stdout) : null
                } catch (e) {
                    root.st = null
                }
            } else {
                root.busy = false
                if (data["exit code"] !== 0 && data.stderr)
                    console.warn("airpodsctl: " + data.stderr)
                refresh.restart()
            }
        }
    }

    Timer {
        id: refresh
        // El fichero se reescribe en cada cambio: leerlo cada 3 s basta (2 s con el panel abierto).
        interval: root.expanded ? 2000 : 3000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: executable.connectSource(root.readCmd)
    }

    Plasmoid.icon: "audio-headphones"
    Plasmoid.status: (st && (lowestPod() >= 0 || field("case"))) ? PlasmaCore.Types.ActiveStatus
                                                                  : PlasmaCore.Types.PassiveStatus
    toolTipMainText: st ? (st.name || st.model_name || "AirPods") : "AirPods"
    toolTipSubText: st ? (tr("Izquierdo") + " " + batteryText(field("left")) + " · " + tr("Derecho") + " "
                          + batteryText(field("right")) + " · " + tr("Caja") + " " + batteryText(field("case")))
                       : tr("airpodsd no está en ejecución")

    compactRepresentation: MouseArea {
        Layout.minimumWidth: row.implicitWidth
        onClicked: root.expanded = !root.expanded
        RowLayout {
            id: row
            anchors.fill: parent
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                source: "audio-headphones"
                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                Layout.preferredHeight: Kirigami.Units.iconSizes.small
            }
            PlasmaComponents3.Label {
                visible: root.lowestPod() >= 0
                text: root.lowestPod() + " %"
                color: root.lowestPod() <= root.lowBattery ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            }
        }
    }

    fullRepresentation: PlasmaExtras.Representation {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 18
        Layout.preferredHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2

        header: PlasmaExtras.PlasmoidHeading {
            PlasmaExtras.Heading {
                level: 3
                text: root.st ? (root.st.name || root.st.model_name || "AirPods") : "AirPods"
            }
        }

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Label {
                visible: root.st === null
                text: root.tr("airpodsd no está en ejecución") + "\nsystemctl --user start airpodsd"
                opacity: 0.7
            }

            Repeater {
                model: root.st ? [["left", root.tr("Izquierdo")], ["right", root.tr("Derecho")], ["case", root.tr("Caja")]] : []
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    PlasmaComponents3.Label { text: modelData[1]; Layout.fillWidth: true }
                    PlasmaComponents3.Label {
                        text: root.batteryText(root.field(modelData[0]))
                        color: (root.field(modelData[0]) && root.field(modelData[0]).level <= root.lowBattery
                                && !root.field(modelData[0]).charging) ? Kirigami.Theme.negativeTextColor
                                                                       : Kirigami.Theme.textColor
                    }
                }
            }

            PlasmaComponents3.Label {
                visible: root.st !== null
                opacity: 0.7
                text: root.st ? root.tr(root.st.connected === true ? "Conectados a este equipo"
                                         : root.st.connected === false ? "No conectados" : "No emparejados con este equipo") : ""
            }

            PlasmaComponents3.Button {
                visible: root.st !== null && root.st.connected === false && !!root.st.address
                enabled: !root.busy
                text: root.tr("Conectar a este equipo")
                icon.name: "network-connect"
                onClicked: {
                    root.busy = true
                    executable.connectSource("bluetoothctl connect " + root.shellQuote(root.st.address))
                }
            }

            Kirigami.Heading {
                visible: root.ownAap() && root.st.aap.modes && root.st.aap.modes.length > 0
                level: 5
                text: root.tr("Modo de escucha")
                Layout.topMargin: Kirigami.Units.smallSpacing
            }
            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing
                visible: root.ownAap()
                Repeater {
                    model: root.ownAap() ? (root.st.aap.modes || []) : []
                    delegate: PlasmaComponents3.Button {
                        required property string modelData
                        text: root.modeLabels[modelData] || modelData
                        checkable: true
                        checked: root.st.aap.settings && root.st.aap.settings.listening_mode === modelData
                        enabled: !root.busy
                        onClicked: root.ctl(["mode", modelData])
                    }
                }
            }

            PlasmaComponents3.Switch {
                visible: root.ownAap() && root.st.aap.settings && root.st.aap.settings.conversational_awareness !== undefined
                text: root.tr("Detección de conversación")
                checked: root.ownAap() && root.st.aap.settings.conversational_awareness === true && !root.st.aap.in_call
                enabled: !root.busy && root.ownAap() && !root.st.aap.in_call
                onToggled: root.ctl(["feature", "conversational_awareness", checked ? "on" : "off"])
            }

            Item { Layout.fillHeight: true }
        }
    }
}
