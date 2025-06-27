# Drone Flight Data Generator

A **single-file** Python solution for generating realistic drone flight telemetry data. This tool can simulate various flight patterns with configurable gimbal control, zoom settings, and altitude profiles.

## 🚀 Features

- **Multiple Flight Paths**: Circle, straight, triangle, and hover patterns
- **Realistic Takeoff Simulation**: Configurable elevation, target altitude, and climb rates
- **Advanced Gimbal Control**: Static, oscillating, and rotating yaw/pitch modes
- **Zoom Configuration**: Static and oscillating zoom factors (1.0-3.0x)
- **Three Operation Modes**: Command-line, interactive wizard, and web UI
- **JSON Output**: Compatible with drone playback and simulation tools

## 📋 Requirements

- Python 3.7+
- Flask (for web UI mode): `pip install flask`

## 🛠️ Installation

1. **Download the script**:
   
   ```bash
   # The script is self-contained - just download drone_flight_generator.py
   ```

2. **Install Flask** (only needed for web UI):
   
   ```bash
   pip install flask
   ```

## 🎯 Quick Start

### Command Line Mode

```bash
# Generate a simple circular flight
python drone_flight_generator.py --path circle --center 45.5,-122.7 --radius 80 --duration 180

# Mountain takeoff scenario
python drone_flight_generator.py --path circle --takeoff-elevation 1500 --takeoff-altitude 2000 --climb-rate 3.0
```

### Interactive Wizard

```bash
python drone_flight_generator.py --interactive
```

### Web UI

```bash
python drone_flight_generator.py --web
# Open browser to http://127.0.0.1:5001/
```

## 📖 Usage Guide

### Flight Path Configuration

| Path Type  | Description               | Required Parameters      |
| ---------- | ------------------------- | ------------------------ |
| `circle`   | Circular flight pattern   | `--center`, `--radius`   |
| `straight` | Linear flight path        | `--start`, `--bearing`   |
| `triangle` | Triangular flight pattern | `--center`, `--tri-edge` |
| `hover`    | Stationary hover          | `--start`, `--bearing`   |

### Altitude Configuration

The generator simulates realistic takeoff behavior:

- **Takeoff Elevation**: Starting ground elevation (m ASL)
- **Target Altitude**: Final flight altitude (m ASL)
- **Climb Rate**: Vertical speed during takeoff (m/s)

```bash
# Example: Sea level takeoff with slow climb
python drone_flight_generator.py \
  --path circle \
  --takeoff-elevation 0 \
  --takeoff-altitude 100 \
  --climb-rate 1.5
```

### Gimbal Control

#### Yaw Modes

- **`static`**: Fixed yaw angle relative to heading
- **`oscillating`**: Sine wave oscillation around heading
- **`rotating`**: Continuous rotation at specified rate

#### Pitch Modes

- **`static`**: Fixed pitch angle
- **`oscillating`**: Sine wave oscillation around center pitch

```bash
# Example: Rotating yaw with static pitch
python drone_flight_generator.py \
  --path circle \
  --yaw-mode rotating \
  --yaw-rotation-rate 2.0 \
  --pitch-mode static \
  --pitch-static -45
```

### Zoom Configuration

- **Range**: 1.0x to 3.0x zoom factor
- **Modes**: Static or oscillating between min/max values

```bash
# Example: Oscillating zoom
python drone_flight_generator.py \
  --path circle \
  --zoom-mode oscillating \
  --zoom-min 1.0 \
  --zoom-max 2.5 \
  --zoom-period 30
```

## 🔧 Command Line Options

### Basic Parameters

```bash
--path {circle,straight,triangle,hover}  # Flight path type
--duration INT                           # Flight duration in seconds
--hz INT                                 # Sample rate (Hz)
--outfile FILENAME                       # Output JSON file
```

### Path-Specific Parameters

```bash
# Circle/Triangle
--center LAT,LON                         # Center coordinates
--radius FLOAT                           # Circle radius (m)
--tri-edge FLOAT                         # Triangle edge length (m)

# Straight/Hover
--start LAT,LON                          # Start coordinates
--bearing FLOAT                          # Bearing angle (degrees)
```

### Altitude Parameters

```bash
--takeoff-elevation FLOAT                # Starting elevation (m ASL)
--takeoff-altitude FLOAT                 # Target altitude (m ASL)
--climb-rate FLOAT                       # Climb rate (m/s)
--sine-amp FLOAT                         # Altitude variation amplitude (m)
--sine-period FLOAT                      # Altitude variation period (s)
```

### Gimbal Parameters

```bash
# Yaw Control
--yaw-mode {static,oscillating,rotating} # Yaw behavior mode
--yaw-static FLOAT                       # Static yaw angle (deg)
--yaw-amp FLOAT                          # Yaw oscillation amplitude (deg)
--yaw-period FLOAT                       # Yaw oscillation period (s)
--yaw-rotation-rate FLOAT                # Yaw rotation rate (deg/s)

# Pitch Control
--pitch-mode {static,oscillating}        # Pitch behavior mode
--pitch-static FLOAT                     # Static pitch angle (deg)
--pitch-mid FLOAT                        # Pitch oscillation center (deg)
--pitch-amp FLOAT                        # Pitch oscillation amplitude (deg)
--pitch-period FLOAT                     # Pitch oscillation period (s)
```

### Zoom Parameters

```bash
--zoom-mode {static,oscillating}         # Zoom behavior mode
--zoom-static FLOAT                      # Static zoom factor (1.0-3.0)
--zoom-min FLOAT                         # Minimum zoom factor (1.0-3.0)
--zoom-max FLOAT                         # Maximum zoom factor (1.0-3.0)
--zoom-period FLOAT                      # Zoom oscillation period (s)
```

## 🌐 Web Interface

The web UI provides an intuitive interface for configuring all parameters:

1. **Launch the web server**:
   
   ```bash
   python drone_flight_generator.py --web
   ```

2. **Open your browser** to `http://127.0.0.1:5001/`

3. **Configure your flight** using the form controls

4. **Generate and download** the JSON file automatically

### Web UI Features

- **Dynamic Form Fields**: Shows/hides relevant options based on selected modes
- **Real-time Validation**: Input constraints and error checking
- **Bootstrap Styling**: Clean, responsive interface
- **Auto-download**: Generated files download automatically

## 📊 Output Format

The generator produces JSON files with the following structure:

```json
[
  {
    "data": {
      "latitude": 45.539460,
      "longitude": -122.763940,
      "height": 500.0,
      "elevation": 0,
      "attitude_head": 90.0,
      "attitude_roll": 0.0,
      "attitude_pitch": 0.0,
      "gimbal_pitch": -30.0,
      "gimbal_roll": 0.0,
      "gimbal_yaw": 90.0,
      "zoom_factor": 1.0,
      "speed": 5.0,
      "seconds_elapsed": 0,
      "current_datetime": "2024-01-01T12:00:00",
      "flight_distance": 0.0
    }
  }
]
```

## 🎮 Interactive Mode

The interactive wizard guides you through configuration step-by-step:

```bash
python drone_flight_generator.py --interactive
```

**Features:**

- **Step-by-step prompts** for all parameters
- **Default values** shown for quick setup
- **Context-aware questions** based on selected options
- **Input validation** and error handling

## 📝 Examples

### Example 1: Search Pattern

```bash
python drone_flight_generator.py \
  --path circle \
  --center 45.5,-122.7 \
  --radius 100 \
  --duration 300 \
  --takeoff-elevation 0 \
  --takeoff-altitude 150 \
  --climb-rate 2.0 \
  --yaw-mode oscillating \
  --yaw-amp 45 \
  --yaw-period 60 \
  --pitch-mode static \
  --pitch-static -30 \
  --zoom-mode oscillating \
  --zoom-min 1.0 \
  --zoom-max 2.0 \
  --zoom-period 45
```

### Example 2: Surveillance Mission

```bash
python drone_flight_generator.py \
  --path straight \
  --start 45.5,-122.7 \
  --bearing 45 \
  --duration 600 \
  --takeoff-elevation 100 \
  --takeoff-altitude 300 \
  --climb-rate 3.0 \
  --yaw-mode rotating \
  --yaw-rotation-rate 1.5 \
  --pitch-mode oscillating \
  --pitch-mid -20 \
  --pitch-amp 30 \
  --pitch-period 90 \
  --zoom-mode static \
  --zoom-static 2.5
```

## 🔍 Troubleshooting

### Common Issues

**Port 5000 already in use:**

- The web UI automatically uses port 5001 if 5000 is occupied
- Check the console output for the correct URL

**Flask not installed:**

```bash
pip install flask
```

**Invalid coordinates:**

- Use decimal format: `45.5,-122.7`
- Ensure latitude is between -90 and 90
- Ensure longitude is between -180 and 180

### Error Messages

| Error                         | Solution                                            |
| ----------------------------- | --------------------------------------------------- |
| `ValueError: mutable default` | Update to Python 3.7+ or use `default_factory`      |
| `ActionError: UNKNOWN`        | Check parameter values and ranges                   |
| `Port already in use`         | Use different port or close conflicting application |

## 🤝 Contributing

This is a single-file solution designed for easy deployment. To contribute:

1. **Fork the repository**
2. **Create a feature branch**
3. **Make your changes**
4. **Test thoroughly**
5. **Submit a pull request**

## 📄 License

This project is open source. See the LICENSE file for details.

## 🙏 Acknowledgments

- Inspired by real drone autopilot systems like [PX4](https://mavsdk.mavlink.io/main/en/cpp/guide/taking_off_landing.html) and [DroneKit](https://dronekit-python.readthedocs.io/en/latest/guide/taking_off.html)
- Uses [Flask](https://flask.palletsprojects.com/) for web interface
- Built with Python's [dataclasses](https://docs.python.org/3/library/dataclasses.html) for clean configuration management

---

**Happy flying!** 🚁
