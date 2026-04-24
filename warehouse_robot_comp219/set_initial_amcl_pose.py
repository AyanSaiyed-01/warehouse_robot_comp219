#!/usr/bin/env python3
"""One-shot /initialpose for AMCL (equivalent to RViz '2D Pose Estimate').

Waits for /scan so the sim is live, then republishes the known spawn pose so
AMCL and the map line up with Gazebo, even if the YAML set_initial_pose ran too
early.
"""

import math
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan


def main() -> None:
    rclpy.init()
    node = rclpy.create_node("set_initial_amcl_pose")

    node.declare_parameters(
        "",
        [
            ("x", -4.0),
            ("y", -3.0),
            ("yaw", 0.0),
            ("wait_for_scan_timeout", 40.0),
            ("settle_s", 1.0),
        ],
    )
    x = node.get_parameter("x").get_parameter_value().double_value
    y = node.get_parameter("y").get_parameter_value().double_value
    yaw = node.get_parameter("yaw").get_parameter_value().double_value
    timeout = node.get_parameter("wait_for_scan_timeout").get_parameter_value().double_value
    settle = node.get_parameter("settle_s").get_parameter_value().double_value

    got_scan = [False]

    def _on_scan(_msg: LaserScan) -> None:
        got_scan[0] = True

    node.create_subscription(LaserScan, "/scan", _on_scan, 10)
    t0 = time.time()
    node.get_logger().info("Waiting for /scan (sim + laser ready)...")
    while rclpy.ok() and (time.time() - t0) < timeout and not got_scan[0]:
        rclpy.spin_once(node, timeout_sec=0.1)
    if not got_scan[0]:
        node.get_logger().warn("Timeout waiting for /scan; publishing /initialpose anyway.")
    time.sleep(max(0.0, settle))
    for _ in range(10):
        rclpy.spin_once(node, timeout_sec=0.05)

    qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    pub = node.create_publisher(
        PoseWithCovarianceStamped, "/initialpose", qos
    )
    time.sleep(0.3)
    out = PoseWithCovarianceStamped()
    out.header.stamp = node.get_clock().now().to_msg()
    out.header.frame_id = "map"
    out.pose.pose.position.x = x
    out.pose.pose.position.y = y
    out.pose.pose.position.z = 0.0
    out.pose.pose.orientation.z = math.sin(yaw / 2.0)
    out.pose.pose.orientation.w = math.cos(yaw / 2.0)
    out.pose.covariance[0] = 0.1
    out.pose.covariance[7] = 0.1
    out.pose.covariance[35] = 0.1

    pub.publish(out)
    for _ in range(5):
        rclpy.spin_once(node, timeout_sec=0.05)
    node.get_logger().info(
        f"Published /initialpose in map: x={x}, y={y}, yaw={yaw}"
    )
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
