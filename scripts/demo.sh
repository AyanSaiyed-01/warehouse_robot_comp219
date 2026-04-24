#!/usr/bin/env bash
# Full-stack demo launcher:
#   1. kills any leftover ROS/Gazebo processes
#   2. starts Gazebo sim in the background
#   3. waits until /odom is publishing
#   4. starts Nav2 in the background
#   5. waits until all Nav2 lifecycle nodes are 'active'
#   6. hands over to the interactive menu client in the foreground
#
# Run this from ONE terminal. Ctrl+C cleans everything up on exit.

set -u

SOURCE_ROS=". /opt/ros/jazzy/setup.bash && . /root/install/setup.bash"

cleanup() {
  echo
  echo "[demo] shutting down..."
  pkill -P $$ 2>/dev/null
  # Nuke anything we spawned regardless of parent
  ps -ef | grep -E "(gz sim|parameter_bridge|ros_gz|controller_server|planner_server|smoother_server|behavior_server|waypoint_follower|map_server|amcl|lifecycle_manager|odom_tf_publisher|static_transform_publisher|ros2 launch warehouse_robot_comp219)" \
    | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null
  exit 0
}
trap cleanup INT TERM EXIT

echo "[demo] step 0: killing leftovers..."
ps -ef | grep -E "(gz sim|parameter_bridge|ros_gz|controller_server|planner_server|smoother_server|behavior_server|waypoint_follower|map_server|amcl|lifecycle_manager|odom_tf_publisher|static_transform_publisher|nav_menu_client|ros2 launch warehouse_robot_comp219)" \
  | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null
ros2 daemon stop &>/dev/null || true
sleep 2

mkdir -p /tmp/demo-logs
SIM_LOG=/tmp/demo-logs/sim.log
NAV_LOG=/tmp/demo-logs/nav2.log
: > "$SIM_LOG"; : > "$NAV_LOG"

echo "[demo] step 1: launching Gazebo sim ($SIM_LOG)..."
bash -c "$SOURCE_ROS && ros2 launch warehouse_robot_comp219 sim.launch.py" \
  > "$SIM_LOG" 2>&1 &
SIM_PID=$!

echo "[demo] step 2: waiting for /odom..."
for i in {1..30}; do
  sleep 2
  COUNT=$(bash -c "$SOURCE_ROS && timeout 2 ros2 topic echo /odom --once 2>/dev/null | wc -l")
  if [ "$COUNT" -gt 5 ]; then
    echo "[demo] /odom is publishing"
    break
  fi
  echo "[demo]   ...still waiting ($i/30)"
  if [ "$i" -eq 30 ]; then
    echo "[demo] ERROR: /odom never appeared. Check $SIM_LOG"
    exit 1
  fi
done

echo "[demo] step 3: launching Nav2 ($NAV_LOG)..."
bash -c "$SOURCE_ROS && ros2 launch warehouse_robot_comp219 nav2.launch.py use_sim_time:=true" \
  > "$NAV_LOG" 2>&1 &
NAV_PID=$!

echo "[demo] step 4: waiting for both Nav2 lifecycle managers to report 'Managed nodes are active'..."
LOC_OK=0
NAV_OK=0
for i in {1..60}; do
  sleep 1
  if [ "$LOC_OK" -eq 0 ] && grep -q "lifecycle_manager_localization.*Managed nodes are active" "$NAV_LOG"; then
    echo "[demo]   localization up"
    LOC_OK=1
  fi
  if [ "$NAV_OK" -eq 0 ] && grep -q "lifecycle_manager_navigation.*Managed nodes are active" "$NAV_LOG"; then
    echo "[demo]   navigation up"
    NAV_OK=1
  fi
  if [ "$LOC_OK" -eq 1 ] && [ "$NAV_OK" -eq 1 ]; then
    echo "[demo] Nav2 is fully up"
    sleep 2
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "[demo] ERROR: Nav2 did not fully activate. See $NAV_LOG"
    exit 1
  fi
done

echo
echo "========================================"
echo "  Nav2 ready. Launching menu client..."
echo "  (Ctrl+C here exits everything.)"
echo "========================================"
echo

bash -c "$SOURCE_ROS && ros2 run warehouse_robot_comp219 nav_menu_client"
