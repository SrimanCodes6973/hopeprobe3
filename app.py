"""HOPEPROBE 3.0 - SEARCH, DETECT, RESCUE.  Streamlit control dashboard.

Run:  streamlit run app.py
"""
from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

from hopeprobe import config
from hopeprobe.camera import CameraMonitor
from hopeprobe.serial_link import CMD_NAMES, SerialLink, list_serial_ports

st.set_page_config(page_title="HOPEPROBE 3.0", layout="wide")

# ----------------------------------------------------------------- singletons
@st.cache_resource
def get_link() -> SerialLink:
    return SerialLink()


@st.cache_resource
def get_camera() -> CameraMonitor:
    return CameraMonitor(get_link().log)


link = get_link()
cam = get_camera()

# ---------------------------------------------------------------------- style
CSS = """
<style>
html, body, [class*="css"], .stApp { font-family: 'JetBrains Mono','DejaVu Sans Mono',monospace !important; }
.stApp { background:#0b0c0a; }
header[data-testid="stHeader"] { background:transparent; }
.block-container { padding-top:1.2rem; max-width:1500px; }
section[data-testid="stSidebar"] { background:#101210; border-right:1px solid #2c3326; }
.hp-header { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px;
  background:#121411; border:1px solid #3a4231; border-left:6px solid #6b7f3a; padding:12px 18px; margin-bottom:14px; }
.hp-title { font-size:1.9rem; font-weight:700; letter-spacing:.12em; color:#a3b46a; }
.hp-tag { display:block; font-size:.75rem; letter-spacing:.3em; color:#7d8a63; }
.hp-chips { display:flex; flex-wrap:wrap; gap:8px; }
.chip { border:1px solid #3a4231; background:#0e100d; padding:5px 10px; font-size:.78rem; color:#9aa585; }
.chip b { color:#c9d1b8; }
.ok { color:#8fbf4a !important; } .warn { color:#e0902f !important; } .bad { color:#d9503a !important; } .off { color:#6f7766 !important; }
.panel { background:#121411; border:1px solid #2f3629; padding:12px 14px; margin-bottom:12px; }
.panel h4 { margin:0 0 8px 0; font-size:.8rem; letter-spacing:.18em; color:#8a9a5b; border-bottom:1px solid #2f3629; padding-bottom:6px; }
.panel .sub { color:#6f7766; font-size:.7rem; letter-spacing:.05em; }
.stat { font-size:1.9rem; font-weight:700; color:#c9d1b8; }
.stat small { font-size:.8rem; color:#7d8a63; font-weight:400; }
.lbl { font-size:.68rem; letter-spacing:.15em; color:#6f7766; }
.row { display:flex; justify-content:space-between; border-bottom:1px dotted #2a3024; padding:4px 0; font-size:.8rem; color:#9aa585; }
.row span:last-child { color:#c9d1b8; text-align:right; }
.camera { aspect-ratio:4/3; width:100%; background:#080908; border:1px dashed #3a4231; display:flex; flex-direction:column;
  align-items:center; justify-content:center; color:#5b6350; letter-spacing:.2em; text-align:center; }
.camera img { width:100%; height:100%; object-fit:contain; }
.log { height:300px; overflow-y:auto; background:#0a0b09; border:1px solid #2a3024; padding:8px; font-size:.74rem; line-height:1.5; }
.log div { border-bottom:1px solid #151813; }
.log .t { color:#5b6350; } .lv-INFO{color:#8a9a5b} .lv-SENSOR{color:#7aa0a0} .lv-CMD{color:#c9d1b8}
.lv-WARN{color:#e0902f} .lv-ERROR{color:#d9503a}
.stButton>button { background:#1a1d17; color:#c9d1b8; border:1px solid #4a5539; border-radius:0; height:3.2rem;
  letter-spacing:.12em; font-weight:700; font-family:inherit; }
.stButton>button:hover { border-color:#8a9a5b; color:#fff; background:#222719; }
.st-key-estop button { background:#6e1d12; border:2px solid #d9503a; color:#fff; height:3.6rem; }
.st-key-estop button:hover { background:#8a2415; border-color:#ff7a5f; }
.st-key-b_stop button { border-color:#e0902f; color:#e0902f; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# -------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### CONFIGURATION")
    st.markdown("**ESP32 serial link**")
    port = st.text_input("Serial port", value=link.port)
    detected = list_serial_ports()
    st.caption("Detected: " + (", ".join(detected) if detected else "none"))
    baud = st.selectbox(
        "Baud rate", config.BAUD_CHOICES,
        index=config.BAUD_CHOICES.index(link.baud) if link.baud in config.BAUD_CHOICES else 2)
    c1, c2 = st.columns(2)
    if c1.button("CONNECT", use_container_width=True):
        ok, msg = link.connect(port, baud)
        (st.success if ok else st.error)(msg)
    if c2.button("DISCONNECT", use_container_width=True):
        link.disconnect()
        st.info("Disconnected")

    st.markdown("---")
    st.markdown("**Modules**")
    link.thermal_enabled = st.checkbox("Thermal sensor (MLX90614)", value=link.thermal_enabled)
    cam_on = st.checkbox("ESP32-CAM", value=cam.enabled)
    cam_url = st.text_input("Camera stream URL", value=cam.url,
                            placeholder="http://192.168.4.1:81/stream")
    cam.configure(cam_url, cam_on)

# --------------------------------------------------------------------- helpers
def esc(x) -> str:
    return html.escape(str(x))


def chip(label: str, value: str, cls: str = "") -> str:
    return f'<div class="chip">{esc(label)}: <b class="{cls}">{esc(value)}</b></div>'


def row(label: str, value: str, cls: str = "") -> str:
    return f'<div class="row"><span>{esc(label)}</span><span class="{cls}">{esc(value)}</span></div>'


def panel(title: str, body: str, sub: str = "") -> str:
    s = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return f'<div class="panel"><h4>{esc(title)}</h4>{s}{body}</div>'


def robot_status(s: dict) -> tuple[str, str]:
    if not s["connected"]:
        return "UNAVAILABLE", "off"
    if not s["alive"]:
        return "NO DATA", "warn"
    ack = s["last_ack"]
    if ack is None:
        return "STANDBY", "ok"
    if ack == "S":
        return "STOPPED", "warn"
    return f"MOVING {CMD_NAMES.get(ack, ack)}", "ok"


def thermal_state(s: dict) -> tuple[str, str]:
    if not s["thermal_enabled"]:
        return "DISABLED", "off"
    if s.get("thermal_simulated"):
        return "DEMO DATA", "warn"
    if not s["connected"]:
        return "DISCONNECTED", "bad"
    if not s["alive"]:
        return "NO DATA", "warn"
    if s["mlx_ok"] is False:
        return "SENSOR FAULT", "bad"
    if s["thermal"] is not None:
        return "ONLINE", "ok"
    return "WAITING", "warn"


def cam_cls(status: str) -> str:
    return {"CONNECTED": "ok", "DISCONNECTED": "bad"}.get(status, "off")


# ------------------------------------------------------------------- dashboard
def do_cmd(cmd: str) -> None:
    ok, msg = link.send_command(cmd)
    st.session_state["ctl_msg"] = (ok, msg)


@st.fragment(run_every=config.REFRESH_S)
def dashboard() -> None:
    s = link.snapshot()
    cam_status = cam.status

    # ---- A. header
    sys_txt, sys_cls = ("ONLINE", "ok") if s["alive"] else ("OFFLINE", "bad")
    if not s["connected"]:
        esp_txt, esp_cls = "DISCONNECTED", "bad"
    elif not s["alive"]:
        esp_txt, esp_cls = "NO DATA", "warn"
    else:
        esp_txt, esp_cls = "CONNECTED", "ok"
    rb_txt, rb_cls = robot_status(s)
    st.markdown(
        '<div class="hp-header"><div><span class="hp-title">HOPEPROBE 3.0</span>'
        '<span class="hp-tag">SEARCH · DETECT · RESCUE</span></div><div class="hp-chips">'
        + chip("SYSTEM", sys_txt, sys_cls) + chip("ESP32", esp_txt, esp_cls)
        + chip("ROBOT", rb_txt, rb_cls)
        + chip("TIME", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        + "</div></div>", unsafe_allow_html=True)

    left, right = st.columns([3, 2])

    # ---- C. camera
    with left:
        if cam.enabled and cam.url:
            feed = (
                f'<div class="camera">'
                f'<img src="{esc(cam.url)}" alt="ESP32-CAM">'
                f'</div>'
            )
        else:
            msg = (
                "CAMERA MODULE DISABLED"
                if not cam.enabled
                else "NO CAMERA CONFIGURED<br><small>set stream URL in sidebar</small>"
            )
            feed = f'<div class="camera"><div>{msg}</div></div>'

        st.markdown(
            panel(
                "CAMERA FEED · ESP32-CAM / RHYX M21-45",
                f'<div class="row"><span>STATUS</span>'
                f'<span class="{cam_cls(cam_status)}">'
                f'{esc(cam_status)}</span></div>'
                + feed
            ),
            unsafe_allow_html=True
        )
    # ---- B. sensors
    with right:
        t_txt, t_cls = thermal_state(s)
        if t_txt in ("ONLINE", "DEMO DATA"):
            obj, amb = s["thermal"]
            heat = config.HEAT_MIN_C <= obj <= config.HEAT_MAX_C
            body = (f'<div class="lbl">OBJECT</div><div class="stat">{obj:.1f}<small> °C</small></div>'
                    f'<div class="lbl">AMBIENT</div><div class="stat">{amb:.1f}<small> °C</small></div>')
            if heat:
                body += '<div class="row"><span>NOTE</span><span class="warn">POSSIBLE HEAT SIGNATURE (indicative)</span></div>'
        else:
            body = ('<div class="lbl">OBJECT</div><div class="stat off">--.-<small> °C</small></div>'
                    '<div class="lbl">AMBIENT</div><div class="stat off">--.-<small> °C</small></div>')
        body += row("STATUS", "ONLINE")
        st.markdown(panel("MLX90614 THERMAL SENSOR", body,
                   "SENSOR READINGS:" if s.get("thermal_simulated")
                   else "I2C · non-contact IR"), unsafe_allow_html=True)



    ctl, info, log = st.columns([2, 2, 3])

    # ---- D. controls
    with ctl:
        st.markdown('<div class="panel"><h4>ROBOT MOVEMENT CONTROL</h4></div>', unsafe_allow_html=True)
        _, a, _ = st.columns(3)
        a.button("FORWARD", key="b_f", use_container_width=True, on_click=do_cmd, args=("F",))
        b1, b2, b3 = st.columns(3)
        b1.button("LEFT", key="b_l", use_container_width=True, on_click=do_cmd, args=("L",))
        b2.button("STOP", key="b_stop", use_container_width=True, on_click=do_cmd, args=("S",))
        b3.button("RIGHT", key="b_r", use_container_width=True, on_click=do_cmd, args=("R",))
        _, c, _ = st.columns(3)
        c.button("BACKWARD", key="b_b", use_container_width=True, on_click=do_cmd, args=("B",))
        st.button("EMERGENCY STOP", key="estop", use_container_width=True, on_click=do_cmd, args=("S",))
        res = st.session_state.get("ctl_msg")
        if res:
            (st.success if res[0] else st.error)(res[1])
        if not s["connected"]:
            st.caption("ESP32 disconnected - commands are blocked, not simulated.")

    # ---- E. system info
    with info:
        t_txt, t_cls = thermal_state(s)
        last = s["last_rx_wall"].strftime("%H:%M:%S") if s["last_rx_wall"] else "never"
        if s["last_ack"]:
            ack = CMD_NAMES.get(s["last_ack"], s["last_ack"])
        else:
            ack = "none"
        body = (row("ESP32", esp_txt, esp_cls) + row("CAMERA", cam_status, cam_cls(cam_status))
                + row("THERMAL SENSOR", "ONLINE")
                + row("LAST DATA", last)
                + row("SERIAL PORT", f'{s["port"]} @ {s["baud"]}' if s["connected"] else f'{s["port"]} (closed)')
                + row("FIRMWARE", s["firmware"] or "unknown")
                + row("LAST ACKED CMD", ack)
                + row("COMMAND PENDING", "YES" if s["cmd_pending"] else "NO"))
        st.markdown(panel("SYSTEM INFORMATION", body), unsafe_allow_html=True)

    # ---- F. event log
    with log:
        lines = "".join(
            f'<div><span class="t">{esc(t)}</span> <span class="lv-{esc(lv)}">[{esc(lv)}]</span> {esc(m)}</div>'
            for t, lv, m in s["events"])
        st.markdown(panel("EVENT LOG", f'<div class="log">{lines}</div>'), unsafe_allow_html=True)


dashboard()
