# 📊 Channel-Sounding-Distance-Plotter

**Channel-Sounding-Distance-Plotter** is a lightweight, standalone visualization and debug tool for real-time BLE localization systems. Built for use with NXP KW45 boards (EVK and LOC), it allows live UART data plotting, BLE terminal interaction, car zone visualization, and data logging — all from a single `.exe` with no dependencies.

---

## 🚀 Features

- 📈 **Real-Time Plotting** of BLE distance data (RSSI / Channel Sounding).
- 💬 **Live Terminal** to view and send UART commands.
- 🚘 **Car Zone Visualization** showing user location graphically.
- 🛠️ **Command Panel** for reset, factory reset, bonding list, passive entry, and more.
- 🔌 **Plug-and-Play** – no Python, no installer; just download and run.
- 🔍 **Auto Port Detection** with adjustable baud rate.
- 💾 **Session Logging** – Save graphs and terminal logs for debugging or analysis.
- 🎛️ **Smooth UI** using multi-threaded architecture to prevent UI blocking.

---

## 🖥️ System Requirements

- Windows 10/11 (64-bit)
- BLE board with UART output (e.g. KW45 EVK or LOC)
- USB-to-Serial or native USB support

---

## 📦 Installation

1. Go to the [**Releases**](https://github.com/YourRepoNameHere/releases) section of this repo.
2. Download the latest `DistancePlotter.exe`.
3. Double-click to run.

> ✅ No installation. No Python. No setup. It just works.

---

## 🧪 Usage Guide

1. Connect your BLE board via USB (make sure UART is active).
2. Launch `DistancePlotter.exe`.
3. Choose the correct COM port and baud rate.
4. Press **Start** to begin live plotting and logging.
5. Use the **terminal** to issue manual commands.
6. Use **buttons** for fast interaction (reset, bond list, etc.).
7. Observe the **zone view** to monitor user position.

---

## 🧰 Terminal & Control Panel Commands

- `#reset` – soft resets the board
- `#factory` – clears bonding and resets config
- `#bondinglist` – prints bonded device list
- `#passive` – activates passive entry logic
- `#bearing` – toggles bearing-based behavior

> These commands are parsed and sent directly to your BLE anchor firmware.

---

## 🖼️ Car Zone View

A graphical visualization shows where the user device is likely located inside the vehicle (e.g., left door, trunk, inside). This feature helps visualize real-world BLE handover and device movement.

---

## 💾 Logging

- Save graph data to file (manual or automatic)
- Save terminal logs for debugging
- Future support for playback and graph export (CSV, PNG)

---

## ❗ Known Issues

- COM ports may not appear if the board is plugged in **after** starting the tool.
- Invalid UART input is ignored by the parser but still shown in the terminal window.

---

## 🔮 Planned Features

- Playback of saved log sessions
- Customizable UI themes and graph styles

---


