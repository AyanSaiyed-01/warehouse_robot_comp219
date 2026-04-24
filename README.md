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

### TF tree

```
map  (published by amcl)
 └── odom  (published by odom_tf_publisher from /odom)
      └── base_footprint  (static transform)
           └── base_link  (static transform)
                └── lidar_link
```

### Goal locations

Coordinates are in the `map` frame (origin is the center of the warehouse):

| # | Name             | x    | y    |
|---|------------------|------|------|
| 1 | Loading Dock     |  3.0 |  2.5 |
| 2 | Dispatch Area    |  3.0 | −2.5 |
| 3 | Charging Station | −3.0 | −2.5 |
| 4 | Inspection Point |  0.0 |  0.0 |

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

You need **four terminals**. In each terminal, first source ROS and the
install space:

```bash
source /opt/ros/jazzy/setup.bash
source /root/install/setup.bash
```

### Terminal 1 — Gazebo simulation

```bash
ros2 launch warehouse_robot_comp219 sim.launch.py
```

Wait until:
- the Gazebo window is open with the robot spawned at `(-4, -3)`, and
- the log shows `OdomTFPublisher started`.

Give it ~5 seconds for `/odom` to start publishing before starting Nav2.

### Terminal 2 — Nav2 stack

```bash
ros2 launch warehouse_robot_comp219 nav2.launch.py use_sim_time:=true
```

Wait until you see **both** of these lines:

```
lifecycle_manager_localization: Managed nodes are active
lifecycle_manager_navigation:   Managed nodes are active
```

### Terminal 3 — C++ menu client

```bash
ros2 run warehouse_robot_comp219 nav_menu_client
```

You should see:

```
========== Navigation Goal Menu ==========
1) Loading Dock      [x=3,  y=2.5]
2) Dispatch Area     [x=3,  y=-2.5]
3) Charging Station  [x=-3, y=-2.5]
4) Inspection Point  [x=0,  y=0]
0) Exit
Select destination:
```

Pick `4` first (shortest path), then try `1`, `2`, `3`. On success you'll
see either `Goal reached successfully.` (NavigateToPose) or
`Goal reached successfully (planner+controller fallback).`.

### Terminal 4 *(optional)* — Health check

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

Then start again from Terminal 1.

---

## What's implemented vs. pending

- [x] Gazebo world, robot URDF with diff-drive + 2D LiDAR
- [x] Static map (PGM/YAML) and AMCL localization
- [x] Nav2 planner + controller + recovery behaviors + smoother
- [x] C++ terminal menu with `NavigateToPose` and planner-only fallback
- [x] Auto-activation of Nav2 lifecycle from the menu client
- [ ] LLM-based natural-language command interface (future work)
