# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CloudControl is a WiFi-based mobile device group control and monitoring web platform. It manages multiple Android phones simultaneously via uiautomator2 integration, built on an async Python (aiohttp) architecture supporting 1,000+ concurrent device connections.

## Commands

### Running the Server
```bash
python main.py  # Starts server on http://0.0.0.0:8000
```

### Installing Dependencies
```bash
pip3 install -r requirements.txt  # Requires Python 3.10+
```

### Stress Testing
```bash
# Setup mock devices for testing (creates N simulated devices in SQLite)
python setup_stress_test.py setup 100

# Run stress test
python stress_test.py --connections 100 --duration 60

# Cleanup mock devices
python setup_stress_test.py cleanup
```

### System Tuning (view recommended settings)
```bash
python config_high_concurrency.py
```

## Architecture

### Core Layers

**Entry Point**: `main.py` - Creates aiohttp app, configures routes, initializes SQLite database and high-performance services.

**Routing Layer** (`resources/`):
- `routes_control.py` - Main HTTP routes: screenshots, touch events, UI hierarchy, file uploads, shell commands
- `routes_user.py` - Authentication routes
- `nio_channel.py` - NIO-style WebSocket channels for streaming control
- `aio_pool.py` - High-performance connection pooling, thread pools, screenshot caching, batch processing

**Service Layer** (`service/impl/`):
- `phone_service_impl.py` - Device lifecycle (connect, disconnect, heartbeat)
- `device_service_impl.py` - Android automation via uiautomator2 (screenshot, touch, input)
- `file_service_impl.py` - File upload/download management

**Database** (`database/sqlite_helper.py`): Async SQLite wrapper using aiosqlite. Tables: `devices`, `installed_file`.

**Configuration** (`config/default_dev.yaml`): SQLite, Redis, Kafka settings, server port.

### Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /list` | List connected devices |
| `GET /inspector/{udid}/screenshot` | Capture device screenshot (JSON base64) |
| `GET /inspector/{udid}/screenshot/img` | Screenshot as JPEG image |
| `POST /inspector/{udid}/touch` | Send touch event |
| `POST /inspector/{udid}/swipe` | Send swipe gesture |
| `POST /inspector/{udid}/input` | Send text input |
| `POST /inspector/{udid}/keyevent` | Send key events (Enter, Home, Back) |
| `GET /inspector/{udid}/hierarchy` | Get UI hierarchy tree |
| `POST /shell` | Execute shell command on device |
| `POST /api/wifi-connect` | Connect device via WiFi ADB |
| `POST /heartbeat` | Device heartbeat (connection keep-alive) |

### Performance Optimizations

The system uses several optimizations in `aio_pool.py`:
- **SmartConnectionPool**: LRU-based pooling (1,200 max connections, 120s health checks, 600s idle timeout)
- **DeviceThreadPool**: Async execution of blocking device operations (`min(CPU_count * 20, 200)` threads)
- **ScreenshotCache**: LRU cache with 50ms TTL to reduce duplicate requests
- **AsyncBatchProcessor**: Groups operations (batch size 10, 50ms flush interval)
- **Device connection cache** in `routes_control.py`: 60-second cache per device

### Technology Stack

- Python 3.10+ with asyncio
- aiohttp 3.8+ (web framework)
- aiosqlite 0.19+ (async SQLite driver)
- uiautomator2 2.0+ (Android automation)
- Jinja2 templates
- WebSockets for real-time control

## Database Schema

**devices table**:
```
udid (UNIQUE), serial, ip, port, present, ready, using_device, is_server, is_mock,
model, brand, version, sdk, memory (JSON), cpu (JSON), battery (JSON), display (JSON),
owner, provider, agent_version, created_at, updated_at, extra_data (JSON)
```

**installed_file table**:
```
group_name, filename, filesize, upload_time, who, extra_data (JSON)
```

## Notes

- Device communication uses WiFi ADB (default port 7912 for atx-agent)
- All device operations go through uiautomator2's HTTP interface
- The `is_mock` field in devices indicates simulated devices for stress testing
- Chinese language comments throughout the codebase
- Database file location: `database/cloudcontrol.db`
