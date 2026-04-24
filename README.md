# warehouse_robot_comp219

Autonomous navigation of a differential-drive mobile robot in a simulated
indoor warehouse using **ROS 2 Jazzy**, **Gazebo (gz sim)**, and the **Nav2**
stack. A small C++ terminal menu (`nav_menu_client`) lets you pick a
semantic destination and drives the robot there via Nav2's planner +
controller.

---

## Contents

- `urdf/warehouse_robot.urdf` — robot model (diff-drive + 2D LiDAR, spawned
  via `ros_gz_sim create`).
- `worlds/warehouse.world` — Gazebo world with walls, racks/shelves, and
  "dock" floor markers.
- `maps/warehouse_map.{pgm,yaml}` — static occupancy grid for AMCL.
- `launch/sim.launch.py` — Gazebo + `ros_gz_bridge` + `odom_tf_publisher` +
  the `base_footprint → base_link` and `base_link → lidar_link` static TFs.
- `launch/sim_nav2.launch.py` — runs `sim.launch.py`, waits, then `nav2.launch.py`
  so Nav2 never starts before `/odom` and the `odom` frame exist.
- `launch/nav2.launch.py` — `map_server`, `amcl`, `planner_server`,
  `controller_server`, `smoother_server`, `behavior_server`,
  `waypoint_follower`, plus two lifecycle managers (localization +
  navigation).
- `config/nav2_params.yaml` — AMCL, costmaps, DWB controller, planner,
  lifecycle manager parameters.
- `src/nav_menu.cpp` — C++ terminal menu client. Calls
  `ManageLifecycleNodes` to (re)activate Nav2 on startup, subscribes to
  `/amcl_pose` for the start pose, and sends goals via `NavigateToPose` if
  available, otherwise falls back to `ComputePathToPose + FollowPath`.
- `warehouse_robot_comp219/odom_tf_publisher.py` — converts the
  `/odom` topic from the Gazebo diff-drive plugin into a TF
  (`odom → base_footprint`) required by Nav2.
- `warehouse_robot_comp219/ai_nav_client.py` — **AI navigation agent**
  (LangChain + Gemini/OpenAI) that accepts natural-language commands and
  drives the same Nav2 stack: `NavigateToPose` if available, else
  `ComputePathToPose` + `FollowPath` (same idea as the C++ menu).
- `requirements.txt` — Python dependencies for the AI agent
  (`langchain`, `langchain-google-genai`, `langchain-openai`).

### TF tree

```
map  (published by amcl)
 └── odom  (published by odom_tf_publisher from /odom)
      └── base_footprint  (static transform)
           └── base_link  (static transform)
                └── lidar_link
```

### Goal locations

Coordinates are in the `map` frame (origin is the center of the warehouse).
The robot spawns at `(−4, −3)` facing east. Goals are chosen so that most
paths are dominated by a single straight segment along a clear aisle.

| # | Name             | x    | y    | Approach from spawn                       |
|---|------------------|------|------|-------------------------------------------|
| 1 | Loading Dock     |  3.5 | −3.0 | Straight east along the bottom aisle      |
| 2 | Dispatch Area    |  3.5 |  3.0 | East along bottom, then north on the right|
| 3 | Charging Station | −3.5 |  3.0 | Straight north along the west side        |
| 4 | Inspection Point |  0.0 |  0.0 | Into the middle corridor between shelves  |

All goals keep at least 1 m of wall clearance.

---

## Build

From a fresh shell:

```bash
cd /root
source /opt/ros/jazzy/setup.bash
colcon build --packages-select warehouse_robot_comp219 --base-paths /root/robot_project
```

---

## Run the demo

**Both** the C++ menu (`nav_menu_client`) and the Python AI client
(`ai_nav_client.py`) move the same simulated robot: they send goals to
Nav2 (both support `NavigateToPose` when present, and
`ComputePathToPose` + `FollowPath` as a fallback). Use **one** of the two
clients at a time.

In every new terminal, source ROS and this package’s install space first:

```bash
source /opt/ros/jazzy/setup.bash
source /root/install/setup.bash
```

### All-in-one launch (recommended)

Starts Gazebo, waits for the sim stack to be ready, then starts Nav2 so
`controller_server` always sees the `odom` frame. Use **one** terminal:

```bash
ros2 launch warehouse_robot_comp219 sim_nav2.launch.py
```

If Gazebo is slow to start, give Nav2 a longer delay (seconds) before
it comes up:

```bash
ros2 launch warehouse_robot_comp219 sim_nav2.launch.py nav2_start_delay_s:=18.0
```

Wait in the log until you see **both** lines:

```text
lifecycle_manager_localization: Managed nodes are active
lifecycle_manager_navigation:   Managed nodes are active
```

Then open a **second** terminal, source the two `setup.bash` lines above,
and run **either** the C++ menu or the AI client (see below). Skip the
separate `sim` / `nav2` launches in that case.

### Or: two terminals for sim + Nav2 (manual order)

1. **Terminal 1 — Gazebo**

   ```bash
   ros2 launch warehouse_robot_comp219 sim.launch.py
   ```

   Wait until the Gazebo window shows the robot at `(-4, -3)` and the log
   shows `OdomTFPublisher started`. Give it ~5 seconds for `/odom` to run
   before starting Nav2.

2. **Terminal 2 — Nav2**

   ```bash
   ros2 launch warehouse_robot_comp219 nav2.launch.py use_sim_time:=true
   ```

   Wait until the same two `Managed nodes are active` lines appear as
   above. **Do not** start Nav2 before Terminal 1 is ready, or
   `controller_server` will complain about a missing `odom` frame.

### One more terminal — drive the robot (C++ *or* AI)

#### C++ menu — build first if needed, then run

```bash
# After colcon build (see Build), from any sourced shell:
ros2 run warehouse_robot_comp219 nav_menu_client
```

Interactive menu: type `1`–`4` to go to a named place, `0` to exit.

| Key | Place              | map pose (x, y)   |
|-----|--------------------|------------------|
| 1   | Loading Dock       | 3.5, −3.0        |
| 2   | Dispatch Area      | 3.5, 3.0         |
| 3   | Charging Station   | −3.5, 3.0        |
| 4   | Inspection Point   | 0, 0             |
| 0   | Exit               | —                |

On success, you should see `Goal reached successfully.` or
`Goal reached successfully (planner+controller fallback).` Try `4` first
(short path), then `1`–`3`.

#### AI agent — install deps, set API key, then run

```bash
# One-time (Debian/Ubuntu):
pip install --break-system-packages -r /root/robot_project/requirements.txt
```

**Option A — environment file** (if you use `.env` in the project root):

```bash
set -a
source /root/robot_project/.env
set +a
```

**Option B — manual exports** (Gemini is the default provider):

```bash
export GOOGLE_API_KEY=your_gemini_api_key_here
# If you use GEMINI_API_KEY instead: export GOOGLE_API_KEY="$GEMINI_API_KEY"
export GEMINI_MODEL=gemini-2.5-flash
```

Optional **OpenAI** instead of Gemini:

```bash
export AI_NAV_PROVIDER=openai
export OPENAI_API_KEY=sk-...
# export OPENAI_MODEL=gpt-4o-mini
```

Start the agent:

```bash
ros2 run warehouse_robot_comp219 ai_nav_client.py
```

Example session (natural language):

```text
you> take the robot to the charging station
bot> (status when arrived at Charging Station or error text)

you> where are you now?
bot> (pose from /amcl_pose in map frame)

you> go to the inspection point
bot> (status)
```

The agent is built with **LangChain 1.x** (`langchain.agents.create_agent`)
and supports both Gemini and OpenAI. Tools include `list_locations`,
`get_current_pose`, `get_navigation_status`, `navigate_to_location`, and
cancel/navigation control. If API keys are missing or LangChain cannot be
imported, the node falls back to a simple **offline** keyword matcher so
you can still type destination phrases without a model.

### Optional — health check (any extra terminal)

```bash
for n in /map_server /amcl /planner_server /controller_server \
         /smoother_server /behavior_server /waypoint_follower; do
  printf "%-22s " "$n"; ros2 lifecycle get "$n"
done
```

All seven nodes should print `active [3]`.

```bash
# Verify the TF chain is complete
ros2 run tf2_ros tf2_echo map base_link
```

You should see translations/rotations update as the robot moves.

---

## Troubleshooting

### `FollowPath goal was rejected`

Means `controller_server` is not `active`. The menu client now auto-calls
`STARTUP`/`RESUME` on the lifecycle manager and retries once. If it still
fails, check that `/odom` is actually being published (Gazebo sim must be
running with `/odom` bridged):

```bash
ros2 topic hz /odom    # expect ~18 Hz
ros2 topic hz /scan    # expect ~10 Hz
```

### `Invalid frame ID "map"` or `Invalid frame ID "odom"`

Means the TF chain is broken. Check each link in order:

```bash
ros2 run tf2_ros tf2_echo odom base_footprint  # from odom_tf_publisher
ros2 run tf2_ros tf2_echo map  odom            # from amcl
```

If `odom → base_footprint` is missing, the `odom_tf_publisher` node isn't
running (check Terminal 1). If `map → odom` is missing, AMCL didn't receive
an initial pose — `set_initial_pose: true` in `config/nav2_params.yaml`
handles this automatically at startup.

### The robot plans but collides with a wall / `FollowPath was aborted`

The DWB controller tuning and goal locations in this repo assume ≥1.5 m of
clearance from the warehouse walls (at `y = ±4.1`, `x = ±5.1`). If you add
new goals, keep them that far from walls or reduce `inflation_radius` in
`config/nav2_params.yaml` (default `0.55`).

### Clean restart (kill everything)

```bash
ps -ef | grep -E "(gz sim|ros2|ros_gz|parameter_bridge|controller_server|planner_server|smoother_server|behavior_server|waypoint_follower|map_server|amcl|lifecycle_manager|nav_menu_client|odom_tf_publisher|static_transform_publisher|/opt/ros/)" \
  | grep -v grep | awk '{print $2}' | xargs -r kill -9
```

Then start again from Gazebo + Nav2 (`sim_nav2.launch.py` or `sim` then `nav2`).

---

## What's implemented vs. pending

- [x] Gazebo world, robot URDF with diff-drive + 2D LiDAR
- [x] Combined `sim_nav2.launch.py` to start sim before Nav2
- [x] Static map (PGM/YAML) and AMCL localization
- [x] Nav2 planner + controller + recovery behaviors + smoother
- [x] C++ terminal menu with `NavigateToPose` and planner-only fallback
- [x] Auto-activation of Nav2 lifecycle from the menu client
- [x] LLM-based natural-language command interface via LangChain +
      Gemini/OpenAI (`ai_nav_client.py`), with an offline keyword-matcher
      fallback.
