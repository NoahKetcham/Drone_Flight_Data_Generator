#!/usr/bin/env python3
"""
Drone Flight Data Generator
==========================
A **single‑file** solution that can run **three ways**:

1. **Command‑line generator** (same behaviour as before)
2. **Interactive CLI wizard** (`--interactive`)
3. **Web UI** powered by *Flask* (`--web`)

Simply drop this file anywhere in your project.  If you already have the old
`drone_flight_generator.py`, replace it with this one ‑ all previous features
still work!

Quick start
-----------
```bash
# Install Flask once (only needed for --web mode)
$ pip install flask

# 1. Classic CLI (unchanged)
$ python drone_flight_generator.py --path circle --center 45.5,-122.7 --radius 80 --duration 180

# 2. Interactive wizard
$ python drone_flight_generator.py --interactive

# 3. Launch browser UI on http://127.0.0.1:5001/
$ python drone_flight_generator.py --web
```

The generator still outputs JSON that matches the schema your playback tools
expect, but now you can configure flights visually.
"""
from __future__ import annotations

import argparse, json, math, sys, datetime, pathlib, textwrap, io
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Callable

# ───────────────────────────────────────────────────────────────────────────────
# Maths helpers
# ───────────────────────────────────────────────────────────────────────────────

M_PER_DEG_LAT = 111_320.0  # metres in 1° lat (spheroid avg)

def meters_to_latlon_offset(d_m: float, angle_deg: float, lat_c: float) -> Tuple[float, float]:
    """Convert polar offset (*d_m*, *angle*) to Δlat/Δlon degrees at latitude *lat_c*."""
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat_c))
    angle_rad = math.radians(angle_deg)
    dlat = (d_m * math.cos(angle_rad)) / M_PER_DEG_LAT
    dlon = (d_m * math.sin(angle_rad)) / m_per_deg_lon
    return dlat, dlon

# ───────────────────────────────────────────────────────────────────────────────
# Profiles (speed, altitude, gimbal)
# ───────────────────────────────────────────────────────────────────────────────

@dataclass
class SpeedProfile:
    base: float = 5.0               # m s‑1
    sine_amp: float = 0.0           # ±m s‑1 extra
    sine_period: float = 30.0       # s

    def speed(self, t: float) -> float:
        return self.base + self.sine_amp * math.sin(2*math.pi*t/self.sine_period)

@dataclass
class AltitudeProfile:
    takeoff_elevation: float = 0.0        # Starting elevation (m ASL)
    takeoff_altitude: float = 500.0       # Target takeoff altitude (m ASL)
    climb_rate: float = 2.0               # m s‑1 (positive = climbing)
    sine_amp: float = 0.0                 # m
    sine_period: float = 60.0             # s

    def height(self, t: float) -> float:
        # Start at takeoff elevation and climb to target altitude
        if t <= 0:
            return self.takeoff_elevation
        
        # Calculate time to reach target altitude
        altitude_diff = self.takeoff_altitude - self.takeoff_elevation
        if self.climb_rate > 0:
            climb_time = altitude_diff / self.climb_rate
        else:
            climb_time = 0
        
        if t <= climb_time:
            # During climb phase
            h = self.takeoff_elevation + self.climb_rate * t
        else:
            # After reaching target altitude
            h = self.takeoff_altitude
        
        # Add sine wave variation if configured
        if self.sine_amp:
            h += self.sine_amp * math.sin(2*math.pi*t/self.sine_period)
        
        return h

@dataclass
class GimbalProfile:
    # Yaw configuration
    yaw_mode: str = "static"          # static, oscillating, rotating
    yaw_static: float = 0.0           # static yaw angle (deg)
    yaw_amp: float = 90.0             # ±deg relative to heading (for oscillating)
    yaw_period: float = 60.0          # s (for oscillating)
    yaw_rotation_rate: float = 1.0    # deg/s (for rotating)
    
    # Pitch configuration
    pitch_mode: str = "static"        # static, oscillating
    pitch_static: float = -30.0       # static pitch angle (deg)
    pitch_mid: float = -30.0          # center pitch for oscillating (deg)
    pitch_amp: float = 60.0           # peak‑to‑peak deg (for oscillating)
    pitch_period: float = 60.0        # s (for oscillating)
    
    # Roll configuration
    roll_amp: float = 5.0             # deg
    roll_period: float = 40.0         # s

    def yaw(self, heading: float, t: float) -> float:
        if self.yaw_mode == "static":
            return (heading + self.yaw_static) % 360
        elif self.yaw_mode == "oscillating":
            return (heading + self.yaw_amp * math.sin(2*math.pi*t/self.yaw_period)) % 360
        elif self.yaw_mode == "rotating":
            return (heading + self.yaw_rotation_rate * t) % 360
        else:
            return heading % 360

    def pitch(self, t: float) -> float:
        if self.pitch_mode == "static":
            return self.pitch_static
        elif self.pitch_mode == "oscillating":
            return self.pitch_mid + (self.pitch_amp/2) * math.sin(2*math.pi*t/self.pitch_period)
        else:
            return self.pitch_static

    def roll(self, t: float) -> float:
        return self.roll_amp * math.sin(2*math.pi*t/self.roll_period)

@dataclass
class ZoomProfile:
    mode: str = "static"              # static, oscillating
    static_value: float = 1.0         # static zoom factor
    min_value: float = 1.0            # minimum zoom factor
    max_value: float = 3.0            # maximum zoom factor
    period: float = 60.0              # s (for oscillating)

    def zoom_factor(self, t: float) -> float:
        if self.mode == "static":
            return self.static_value
        elif self.mode == "oscillating":
            # Oscillate between min and max values
            range_val = self.max_value - self.min_value
            return self.min_value + (range_val/2) * (1 + math.sin(2*math.pi*t/self.period))
        else:
            return self.static_value

# ───────────────────────────────────────────────────────────────────────────────
# Flight configuration dataclass
# ───────────────────────────────────────────────────────────────────────────────

@dataclass
class FlightConfig:
    path_type: str = "circle"      # circle/straight/triangle/hover
    duration: int = 120             # s
    hz: int = 1                     # samples per second
    # circle / triangle
    center_lat: float = 45.53946
    center_lon: float = -122.76394
    radius_m: float = 60.0          # for circle
    tri_edge_m: float = 120.0       # for triangle
    # straight / hover
    start_lat: float = 45.53946
    start_lon: float = -122.76394
    bearing_deg: float = 90.0

    altitude: AltitudeProfile = field(default_factory=AltitudeProfile)
    speed:    SpeedProfile    = field(default_factory=SpeedProfile)
    gimbal:   GimbalProfile   = field(default_factory=GimbalProfile)
    zoom:     ZoomProfile     = field(default_factory=ZoomProfile)

    def total_pts(self) -> int: return self.duration * self.hz

# ───────────────────────────────────────────────────────────────────────────────
# Path generators
# ───────────────────────────────────────────────────────────────────────────────

PathFunc = Callable[[FlightConfig], List[Tuple[float, float, float]]]

def gen_circle(cfg: FlightConfig) -> List[Tuple[float, float, float]]:
    out = []
    for i in range(cfg.total_pts()):
        frac = i / cfg.total_pts()
        ang = frac * 360.0
        dlat, dlon = meters_to_latlon_offset(cfg.radius_m, ang, cfg.center_lat)
        lat = cfg.center_lat + dlat
        lon = cfg.center_lon + dlon
        heading = (ang + 90) % 360
        out.append((lat, lon, heading))
    return out

def gen_straight(cfg: FlightConfig) -> List[Tuple[float, float, float]]:
    total_dist = cfg.speed.base * cfg.duration  # naive (ignores variability)
    step = total_dist / cfg.total_pts()
    lat0, lon0 = cfg.start_lat, cfg.start_lon
    out = []
    for i in range(cfg.total_pts()):
        d = step * i
        dlat, dlon = meters_to_latlon_offset(d, cfg.bearing_deg, lat0)
        out.append((lat0 + dlat, lon0 + dlon, cfg.bearing_deg % 360))
    return out

def gen_hover(cfg: FlightConfig) -> List[Tuple[float, float, float]]:
    return [(cfg.start_lat, cfg.start_lon, cfg.bearing_deg % 360)] * cfg.total_pts()

def gen_triangle(cfg: FlightConfig) -> List[Tuple[float, float, float]]:
    verts: List[Tuple[float, float]] = []
    for k in range(3):
        ang = 90 + k*120
        dlat, dlon = meters_to_latlon_offset(cfg.tri_edge_m/math.sqrt(3), ang, cfg.center_lat)
        verts.append((cfg.center_lat+dlat, cfg.center_lon+dlon))

    pts_per_edge = cfg.total_pts() // 3 or 1
    out: List[Tuple[float, float, float]] = []
    for e in range(3):
        lat1, lon1 = verts[e]
        lat2, lon2 = verts[(e+1)%3]
        for j in range(pts_per_edge):
            t = j/pts_per_edge
            lat = lat1 + t*(lat2-lat1)
            lon = lon1 + t*(lon2-lon1)
            heading = math.degrees(math.atan2(lon2-lon1, lat2-lat1)) % 360
            out.append((lat, lon, heading))
    while len(out) < cfg.total_pts():
        out.append(out[-1])
    return out

PATHS: Dict[str, PathFunc] = {
    "circle": gen_circle,
    "straight": gen_straight,
    "triangle": gen_triangle,
    "hover": gen_hover,
}

# ───────────────────────────────────────────────────────────────────────────────
# Entry generation
# ───────────────────────────────────────────────────────────────────────────────

def generate_entries(cfg: FlightConfig):
    gen = PATHS[cfg.path_type]
    path_pts = gen(cfg)
    start_time = datetime.datetime.now()

    entries, flight_dist = [], 0.0
    for i, (lat, lon, heading) in enumerate(path_pts):
        t = i / cfg.hz
        speed = cfg.speed.speed(t)
        flight_dist += speed / cfg.hz
        entries.append({
            "data": {
                "latitude":        round(lat, 6),
                "longitude":       round(lon, 6),
                "height":          round(cfg.altitude.height(t), 1),
                "elevation":       0,
                "attitude_head":   round(heading, 1),
                "attitude_roll":   round(cfg.gimbal.roll(t), 2),  # re‑use
                "attitude_pitch":  0.0,
                "gimbal_pitch":    round(cfg.gimbal.pitch(t), 1),
                "gimbal_roll":     round(cfg.gimbal.roll(t), 2),
                "gimbal_yaw":      round(cfg.gimbal.yaw(heading, t), 1),
                "zoom_factor":     round(cfg.zoom.zoom_factor(t), 2),
                "speed":           round(speed, 2),
                "seconds_elapsed": int(t),
                "current_datetime": (start_time + datetime.timedelta(seconds=t)).isoformat(),
                "flight_distance": round(flight_dist, 1),
            }
        })
    return entries

# ───────────────────────────────────────────────────────────────────────────────
# Config helpers (CLI ↔ dataclass)
# ───────────────────────────────────────────────────────────────────────────────

def build_config(ns: argparse.Namespace) -> FlightConfig:
    cfg = FlightConfig(path_type=ns.path, duration=ns.duration, hz=ns.hz)
    if cfg.path_type in {"circle", "triangle"} and ns.center:
        cfg.center_lat, cfg.center_lon = map(float, ns.center.split(","))
    if cfg.path_type == "circle" and ns.radius: cfg.radius_m = ns.radius
    if cfg.path_type == "triangle" and ns.tri_edge: cfg.tri_edge_m = ns.tri_edge
    if cfg.path_type in {"straight", "hover"} and ns.start:
        cfg.start_lat, cfg.start_lon = map(float, ns.start.split(","))
    if cfg.path_type in {"straight", "hover"} and ns.bearing is not None:
        cfg.bearing_deg = ns.bearing
    
    # Update altitude configuration if provided
    if hasattr(ns, 'takeoff_elevation') and ns.takeoff_elevation is not None:
        cfg.altitude.takeoff_elevation = ns.takeoff_elevation
    if hasattr(ns, 'takeoff_altitude') and ns.takeoff_altitude is not None:
        cfg.altitude.takeoff_altitude = ns.takeoff_altitude
    if hasattr(ns, 'climb_rate') and ns.climb_rate is not None:
        cfg.altitude.climb_rate = ns.climb_rate
    if hasattr(ns, 'sine_amp') and ns.sine_amp is not None:
        cfg.altitude.sine_amp = ns.sine_amp
    if hasattr(ns, 'sine_period') and ns.sine_period is not None:
        cfg.altitude.sine_period = ns.sine_period
    
    # Update gimbal configuration if provided
    if hasattr(ns, 'yaw_mode') and ns.yaw_mode:
        cfg.gimbal.yaw_mode = ns.yaw_mode
    if hasattr(ns, 'yaw_static') and ns.yaw_static is not None:
        cfg.gimbal.yaw_static = ns.yaw_static
    if hasattr(ns, 'yaw_amp') and ns.yaw_amp is not None:
        cfg.gimbal.yaw_amp = ns.yaw_amp
    if hasattr(ns, 'yaw_period') and ns.yaw_period is not None:
        cfg.gimbal.yaw_period = ns.yaw_period
    if hasattr(ns, 'yaw_rotation_rate') and ns.yaw_rotation_rate is not None:
        cfg.gimbal.yaw_rotation_rate = ns.yaw_rotation_rate
    
    if hasattr(ns, 'pitch_mode') and ns.pitch_mode:
        cfg.gimbal.pitch_mode = ns.pitch_mode
    if hasattr(ns, 'pitch_static') and ns.pitch_static is not None:
        cfg.gimbal.pitch_static = ns.pitch_static
    if hasattr(ns, 'pitch_mid') and ns.pitch_mid is not None:
        cfg.gimbal.pitch_mid = ns.pitch_mid
    if hasattr(ns, 'pitch_amp') and ns.pitch_amp is not None:
        cfg.gimbal.pitch_amp = ns.pitch_amp
    if hasattr(ns, 'pitch_period') and ns.pitch_period is not None:
        cfg.gimbal.pitch_period = ns.pitch_period
    
    # Update zoom configuration if provided
    if hasattr(ns, 'zoom_mode') and ns.zoom_mode:
        cfg.zoom.mode = ns.zoom_mode
    if hasattr(ns, 'zoom_static') and ns.zoom_static is not None:
        cfg.zoom.static_value = ns.zoom_static
    if hasattr(ns, 'zoom_min') and ns.zoom_min is not None:
        cfg.zoom.min_value = ns.zoom_min
    if hasattr(ns, 'zoom_max') and ns.zoom_max is not None:
        cfg.zoom.max_value = ns.zoom_max
    if hasattr(ns, 'zoom_period') and ns.zoom_period is not None:
        cfg.zoom.period = ns.zoom_period
    
    return cfg

# ───────────────────────────────────────────────────────────────────────────────
# Interactive CLI wizard
# ───────────────────────────────────────────────────────────────────────────────

def interactive_prompt() -> argparse.Namespace:
    print("\n*** Interactive Flight Configurator ***\nPress <Enter> to accept shown defaults.\n")
    def ask(msg, cast, default):
        val = input(f"{msg} [{default}]: ").strip()
        return cast(val) if val else default

    ns = argparse.Namespace()
    ns.path = ask("Path type circle/straight/triangle/hover", str, "circle")
    ns.duration = ask("Duration (s)", int, 120)
    ns.hz = ask("Sample rate (Hz)", int, 1)

    if ns.path in {"circle", "triangle"}:
        ns.center = ask("Center lat,lon", str, "45.53946,-122.76394")
    else:
        ns.center = None

    ns.radius = ask("Circle radius (m)", float, 60.0) if ns.path=="circle" else None
    ns.tri_edge = ask("Triangle edge (m)", float, 120.0) if ns.path=="triangle" else None

    if ns.path in {"straight", "hover"}:
        ns.start = ask("Start lat,lon", str, "45.53946,-122.76394")
        ns.bearing = ask("Bearing (deg)", float, 90.0)
    else:
        ns.start = ns.bearing = None

    # Altitude configuration
    print("\n--- Altitude Configuration ---")
    ns.takeoff_elevation = ask("Takeoff elevation (m ASL)", float, 0.0)
    ns.takeoff_altitude = ask("Target altitude (m ASL)", float, 500.0)
    ns.climb_rate = ask("Climb rate (m/s)", float, 2.0)
    ns.sine_amp = ask("Altitude variation amplitude (m)", float, 0.0)
    ns.sine_period = ask("Altitude variation period (s)", float, 60.0)

    # Gimbal configuration
    print("\n--- Gimbal Configuration ---")
    ns.yaw_mode = ask("Yaw mode (static/oscillating/rotating)", str, "static")
    if ns.yaw_mode == "static":
        ns.yaw_static = ask("Static yaw angle (deg)", float, 0.0)
    elif ns.yaw_mode == "oscillating":
        ns.yaw_amp = ask("Yaw amplitude (deg)", float, 90.0)
        ns.yaw_period = ask("Yaw period (s)", float, 60.0)
    elif ns.yaw_mode == "rotating":
        ns.yaw_rotation_rate = ask("Yaw rotation rate (deg/s)", float, 1.0)

    ns.pitch_mode = ask("Pitch mode (static/oscillating)", str, "static")
    if ns.pitch_mode == "static":
        ns.pitch_static = ask("Static pitch angle (deg)", float, -30.0)
    elif ns.pitch_mode == "oscillating":
        ns.pitch_mid = ask("Pitch center (deg)", float, -30.0)
        ns.pitch_amp = ask("Pitch amplitude (deg)", float, 60.0)
        ns.pitch_period = ask("Pitch period (s)", float, 60.0)

    # Zoom configuration
    print("\n--- Zoom Configuration ---")
    ns.zoom_mode = ask("Zoom mode (static/oscillating)", str, "static")
    if ns.zoom_mode == "static":
        ns.zoom_static = ask("Static zoom factor (1.0-3.0)", float, 1.0)
    elif ns.zoom_mode == "oscillating":
        ns.zoom_min = ask("Min zoom factor (1.0-3.0)", float, 1.0)
        ns.zoom_max = ask("Max zoom factor (1.0-3.0)", float, 3.0)
        ns.zoom_period = ask("Zoom period (s)", float, 60.0)

    ns.outfile = ask("Output filename", str, "flight_data.json")
    return ns

# ───────────────────────────────────────────────────────────────────────────────
# Web UI (Flask)
# ───────────────────────────────────────────────────────────────────────────────

def run_web_ui():
    try:
        from flask import Flask, render_template_string, request, send_file
    except ImportError:
        sys.exit("Flask is not installed. Run 'pip install flask' and try again.")

    app = Flask(__name__)
    DEFAULT_CFG = FlightConfig()

    TEMPLATE = """<!doctype html>
<title>Drone Flight Data Generator</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{padding-top:2rem;padding-bottom:2rem}</style>
<div class=container>
  <h1 class="mb-4">Drone Flight Data Generator</h1>
  <form method=post>
    <div class="row mb-3">
      <div class=col>
        <label class=form-label>Flight path</label>
        <select name=path class="form-select" id=path>
          {% for p in ['circle','straight','triangle','hover'] %}
            <option value="{{p}}" {{'selected' if p==cfg.path_type else ''}}>{{p.title()}}</option>
          {% endfor %}
        </select>
      </div>
      <div class=col>
        <label class=form-label>Duration (s)</label>
        <input type=number name=duration class="form-control" value="{{cfg.duration}}">
      </div>
      <div class=col>
        <label class=form-label>Sample rate (Hz)</label>
        <input type=number name=hz class="form-control" value="{{cfg.hz}}">
      </div>
    </div>
    
    <h5>Circle / Triangle</h5>
    <div class="row mb-3">
      <div class=col>
        <label class=form-label>Center lat,lon</label>
        <input name=center class="form-control" value="{{cfg.center_lat}},{{cfg.center_lon}}">
      </div>
      <div class=col>
        <label class=form-label>Radius (m)</label>
        <input type=number name=radius class="form-control" value="{{cfg.radius_m}}">
      </div>
      <div class=col>
        <label class=form-label>Triangle edge (m)</label>
        <input type=number name=tri_edge class="form-control" value="{{cfg.tri_edge_m}}">
      </div>
    </div>
    
    <h5>Straight / Hover</h5>
    <div class="row mb-3">
      <div class=col>
        <label class=form-label>Start lat,lon</label>
        <input name=start class="form-control" value="{{cfg.start_lat}},{{cfg.start_lon}}">
      </div>
      <div class=col>
        <label class=form-label>Bearing (deg)</label>
        <input type=number name=bearing class="form-control" value="{{cfg.bearing_deg}}">
      </div>
    </div>

    <h5>Altitude Configuration</h5>
    <div class="row mb-3">
      <div class=col>
        <label class=form-label>Takeoff Elevation (m ASL)</label>
        <input type=number name=takeoff_elevation class="form-control" value="{{cfg.altitude.takeoff_elevation}}" step="0.1">
      </div>
      <div class=col>
        <label class=form-label>Target Altitude (m ASL)</label>
        <input type=number name=takeoff_altitude class="form-control" value="{{cfg.altitude.takeoff_altitude}}" step="0.1">
      </div>
      <div class=col>
        <label class=form-label>Climb Rate (m/s)</label>
        <input type=number name=climb_rate class="form-control" value="{{cfg.altitude.climb_rate}}" step="0.1">
      </div>
      <div class=col>
        <label class=form-label>Altitude Variation (m)</label>
        <input type=number name=sine_amp class="form-control" value="{{cfg.altitude.sine_amp}}" step="0.1">
      </div>
      <div class=col>
        <label class=form-label>Variation Period (s)</label>
        <input type=number name=sine_period class="form-control" value="{{cfg.altitude.sine_period}}" step="0.1">
      </div>
    </div>

    <h5>Gimbal Configuration</h5>
    <div class="row mb-3">
      <div class=col>
        <label class=form-label>Yaw Mode</label>
        <select name=yaw_mode class="form-select" id=yaw_mode>
          <option value="static" {{'selected' if cfg.gimbal.yaw_mode=='static' else ''}}>Static</option>
          <option value="oscillating" {{'selected' if cfg.gimbal.yaw_mode=='oscillating' else ''}}>Oscillating</option>
          <option value="rotating" {{'selected' if cfg.gimbal.yaw_mode=='rotating' else ''}}>Rotating</option>
        </select>
      </div>
      <div class=col yaw-static>
        <label class=form-label>Static Yaw (deg)</label>
        <input type=number name=yaw_static class="form-control" value="{{cfg.gimbal.yaw_static}}" step="0.1">
      </div>
      <div class=col yaw-osc>
        <label class=form-label>Yaw Amplitude (deg)</label>
        <input type=number name=yaw_amp class="form-control" value="{{cfg.gimbal.yaw_amp}}" step="0.1">
      </div>
      <div class=col yaw-osc>
        <label class=form-label>Yaw Period (s)</label>
        <input type=number name=yaw_period class="form-control" value="{{cfg.gimbal.yaw_period}}" step="0.1">
      </div>
      <div class=col yaw-rot>
        <label class=form-label>Yaw Rotation Rate (deg/s)</label>
        <input type=number name=yaw_rotation_rate class="form-control" value="{{cfg.gimbal.yaw_rotation_rate}}" step="0.1">
      </div>
    </div>

    <div class="row mb-3">
      <div class=col>
        <label class=form-label>Pitch Mode</label>
        <select name=pitch_mode class="form-select" id=pitch_mode>
          <option value="static" {{'selected' if cfg.gimbal.pitch_mode=='static' else ''}}>Static</option>
          <option value="oscillating" {{'selected' if cfg.gimbal.pitch_mode=='oscillating' else ''}}>Oscillating</option>
        </select>
      </div>
      <div class=col pitch-static>
        <label class=form-label>Static Pitch (deg)</label>
        <input type=number name=pitch_static class="form-control" value="{{cfg.gimbal.pitch_static}}" step="0.1">
      </div>
      <div class=col pitch-osc>
        <label class=form-label>Pitch Center (deg)</label>
        <input type=number name=pitch_mid class="form-control" value="{{cfg.gimbal.pitch_mid}}" step="0.1">
      </div>
      <div class=col pitch-osc>
        <label class=form-label>Pitch Amplitude (deg)</label>
        <input type=number name=pitch_amp class="form-control" value="{{cfg.gimbal.pitch_amp}}" step="0.1">
      </div>
      <div class=col pitch-osc>
        <label class=form-label>Pitch Period (s)</label>
        <input type=number name=pitch_period class="form-control" value="{{cfg.gimbal.pitch_period}}" step="0.1">
      </div>
    </div>

    <h5>Zoom Configuration</h5>
    <div class="row mb-3">
      <div class=col>
        <label class=form-label>Zoom Mode</label>
        <select name=zoom_mode class="form-select" id=zoom_mode>
          <option value="static" {{'selected' if cfg.zoom.mode=='static' else ''}}>Static</option>
          <option value="oscillating" {{'selected' if cfg.zoom.mode=='oscillating' else ''}}>Oscillating</option>
        </select>
      </div>
      <div class=col zoom-static>
        <label class=form-label>Static Zoom Factor</label>
        <input type=number name=zoom_static class="form-control" value="{{cfg.zoom.static_value}}" min="1.0" max="3.0" step="0.1">
      </div>
      <div class=col zoom-osc>
        <label class=form-label>Min Zoom Factor</label>
        <input type=number name=zoom_min class="form-control" value="{{cfg.zoom.min_value}}" min="1.0" max="3.0" step="0.1">
      </div>
      <div class=col zoom-osc>
        <label class=form-label>Max Zoom Factor</label>
        <input type=number name=zoom_max class="form-control" value="{{cfg.zoom.max_value}}" min="1.0" max="3.0" step="0.1">
      </div>
      <div class=col zoom-osc>
        <label class=form-label>Zoom Period (s)</label>
        <input type=number name=zoom_period class="form-control" value="{{cfg.zoom.period}}" step="0.1">
      </div>
    </div>

    <button class="btn btn-primary" type=submit>Generate JSON</button>
  </form>
  <p class="mt-4 text-muted">A JSON file will download automatically.</p>
</div>
<script>
const pathSel=document.getElementById('path');
const yawModeSel=document.getElementById('yaw_mode');
const pitchModeSel=document.getElementById('pitch_mode');
const zoomModeSel=document.getElementById('zoom_mode');

function togglePath(){const v=pathSel.value;
  const circleTri=['circle','triangle'].includes(v);
  const straightHover=['straight','hover'].includes(v);
  document.querySelectorAll('[name=center],[name=radius],[name=tri_edge]').forEach(e=>e.closest('.col').style.display=circleTri?'block':'none');
  document.querySelector('[name=tri_edge]').closest('.col').style.display=(v==='triangle')?'block':'none');
  document.querySelectorAll('[name=start],[name=bearing]').forEach(e=>e.closest('.col').style.display=straightHover?'block':'none');
}

function toggleYaw(){const v=yawModeSel.value;
  document.querySelectorAll('.yaw-static').forEach(e=>e.style.display=(v==='static')?'block':'none');
  document.querySelectorAll('.yaw-osc').forEach(e=>e.style.display=(v==='oscillating')?'block':'none');
  document.querySelectorAll('.yaw-rot').forEach(e=>e.style.display=(v==='rotating')?'block':'none');
}

function togglePitch(){const v=pitchModeSel.value;
  document.querySelectorAll('.pitch-static').forEach(e=>e.style.display=(v==='static')?'block':'none');
  document.querySelectorAll('.pitch-osc').forEach(e=>e.style.display=(v==='oscillating')?'block':'none');
}

function toggleZoom(){const v=zoomModeSel.value;
  document.querySelectorAll('.zoom-static').forEach(e=>e.style.display=(v==='static')?'block':'none');
  document.querySelectorAll('.zoom-osc').forEach(e=>e.style.display=(v==='oscillating')?'block':'none');
}

pathSel.addEventListener('change',togglePath);
yawModeSel.addEventListener('change',toggleYaw);
pitchModeSel.addEventListener('change',togglePitch);
zoomModeSel.addEventListener('change',toggleZoom);

window.addEventListener('DOMContentLoaded',function(){
  togglePath();toggleYaw();togglePitch();toggleZoom();
});
</script>
"""

    @app.route('/', methods=['GET', 'POST'])
    def index():
        cfg = DEFAULT_CFG
        if request.method == 'POST':
            # Parse form data
            args = argparse.Namespace(
                path=request.form['path'],
                duration=int(request.form['duration']),
                hz=int(request.form['hz']),
                center=request.form.get('center'),
                radius=float(request.form.get('radius') or 0) or None,
                tri_edge=float(request.form.get('tri_edge') or 0) or None,
                start=request.form.get('start'),
                bearing=float(request.form.get('bearing') or 0) or None,
                outfile='web.json')
            
            cfg = build_config(args)
            
            # Update altitude configuration
            cfg.altitude.takeoff_elevation = float(request.form.get('takeoff_elevation', 0.0))
            cfg.altitude.takeoff_altitude = float(request.form.get('takeoff_altitude', 500.0))
            cfg.altitude.climb_rate = float(request.form.get('climb_rate', 2.0))
            cfg.altitude.sine_amp = float(request.form.get('sine_amp', 0.0))
            cfg.altitude.sine_period = float(request.form.get('sine_period', 60.0))
            
            # Update gimbal configuration
            cfg.gimbal.yaw_mode = request.form.get('yaw_mode', 'static')
            cfg.gimbal.yaw_static = float(request.form.get('yaw_static', 0))
            cfg.gimbal.yaw_amp = float(request.form.get('yaw_amp', 90))
            cfg.gimbal.yaw_period = float(request.form.get('yaw_period', 60))
            cfg.gimbal.yaw_rotation_rate = float(request.form.get('yaw_rotation_rate', 1))
            
            cfg.gimbal.pitch_mode = request.form.get('pitch_mode', 'static')
            cfg.gimbal.pitch_static = float(request.form.get('pitch_static', -30))
            cfg.gimbal.pitch_mid = float(request.form.get('pitch_mid', -30))
            cfg.gimbal.pitch_amp = float(request.form.get('pitch_amp', 60))
            cfg.gimbal.pitch_period = float(request.form.get('pitch_period', 60))
            
            # Update zoom configuration
            cfg.zoom.mode = request.form.get('zoom_mode', 'static')
            cfg.zoom.static_value = float(request.form.get('zoom_static', 1.0))
            cfg.zoom.min_value = float(request.form.get('zoom_min', 1.0))
            cfg.zoom.max_value = float(request.form.get('zoom_max', 3.0))
            cfg.zoom.period = float(request.form.get('zoom_period', 60))
            
            data = json.dumps(generate_entries(cfg), indent=2).encode()
            buf = io.BytesIO(data)
            buf.seek(0)
            fname = f"{cfg.path_type}_{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
            return send_file(buf, as_attachment=True, download_name=fname, mimetype='application/json')

        return render_template_string(TEMPLATE, cfg=cfg)

    print("* Running on http://127.0.0.1:5001/ (Ctrl+C to quit)")
    app.run(debug=False, port=5001)

# ───────────────────────────────────────────────────────────────────────────────
# Main entry‑point
# ───────────────────────────────────────────────────────────────────────────────

def main(argv: List[str] | None = None):
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(__doc__))
    p.add_argument('--path', choices=PATHS.keys(), default='circle')
    p.add_argument('--duration', type=int, default=120)
    p.add_argument('--hz', type=int, default=1)
    p.add_argument('--center')
    p.add_argument('--radius', type=float)
    p.add_argument('--start')
    p.add_argument('--bearing', type=float)
    p.add_argument('--tri_edge', type=float)
    p.add_argument('--outfile', default='flight_data.json')
    p.add_argument('--interactive', action='store_true')
    p.add_argument('--web', action='store_true', help='Launch Flask UI')
    
    # Altitude arguments
    p.add_argument('--takeoff-elevation', type=float, default=0.0)
    p.add_argument('--takeoff-altitude', type=float, default=500.0)
    p.add_argument('--climb-rate', type=float, default=2.0)
    p.add_argument('--sine-amp', type=float, default=0.0)
    p.add_argument('--sine-period', type=float, default=60.0)
    
    # Gimbal arguments
    p.add_argument('--yaw-mode', choices=['static', 'oscillating', 'rotating'], default='static')
    p.add_argument('--yaw-static', type=float, default=0.0)
    p.add_argument('--yaw-amp', type=float, default=90.0)
    p.add_argument('--yaw-period', type=float, default=60.0)
    p.add_argument('--yaw-rotation-rate', type=float, default=1.0)
    
    p.add_argument('--pitch-mode', choices=['static', 'oscillating'], default='static')
    p.add_argument('--pitch-static', type=float, default=-30.0)
    p.add_argument('--pitch-mid', type=float, default=-30.0)
    p.add_argument('--pitch-amp', type=float, default=60.0)
    p.add_argument('--pitch-period', type=float, default=60.0)
    
    # Zoom arguments
    p.add_argument('--zoom-mode', choices=['static', 'oscillating'], default='static')
    p.add_argument('--zoom-static', type=float, default=1.0)
    p.add_argument('--zoom-min', type=float, default=1.0)
    p.add_argument('--zoom-max', type=float, default=3.0)
    p.add_argument('--zoom-period', type=float, default=60.0)

    args = p.parse_args(argv)

    if args.web:
        run_web_ui()
        return

    if args.interactive:
        args = interactive_prompt()

    cfg = build_config(args)
    entries = generate_entries(cfg)
    path = pathlib.Path(args.outfile)
    path.write_text(json.dumps(entries, indent=2))
    print(f"Wrote {len(entries)} points to {path.resolve()}")

    pitch = [e['data']['gimbal_pitch'] for e in entries]
    yaw   = [e['data']['gimbal_yaw']   for e in entries]
    spd   = [e['data']['speed']        for e in entries]
    zoom  = [e['data']['zoom_factor']  for e in entries]
    print(f"gimbal_pitch: {min(pitch):.1f} … {max(pitch):.1f}")
    print(f"gimbal_yaw:   {min(yaw):.1f} … {max(yaw):.1f}")
    print(f"speed:        {min(spd):.1f} … {max(spd):.1f}")
    print(f"zoom_factor:  {min(zoom):.2f} … {max(zoom):.2f}")

if __name__ == '__main__':
    main()
