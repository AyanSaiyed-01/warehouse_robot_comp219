"""Gazebo + Nav2 in one process.

Nav2's controller_server must see the ``odom`` frame (``odom`` -> ``base_footprint``)
from ``odom_tf_publisher`` in *sim*. If you start ``nav2.launch.py`` with no sim
running, you get endless ``Invalid frame ID odom`` — not a stack bug, only order.

This launch runs ``sim.launch.py`` first, waits for Gazebo/bridge/odom TF, then
starts ``nav2.launch.py`` (no bt_navigator).
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    pkg = get_package_share_directory("warehouse_robot_comp219")

    delay = LaunchConfiguration("nav2_start_delay_s")

    declare_delay = DeclareLaunchArgument(
        "nav2_start_delay_s",
        default_value="12.0",
        description="Seconds to wait after starting Gazebo before launching Nav2 "
        "(allow /odom and odom->base_footprint TF).",
    )

    sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg, "launch", "sim.launch.py")
        )
    )

    # Delay gives gz sim + bridge + odom_tf_publisher time; Nav2 then activates cleanly.
    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg, "launch", "nav2.launch.py")
        ),
        launch_arguments=[("use_sim_time", "true")],
    )

    return LaunchDescription(
        [
            declare_delay,
            sim,
            TimerAction(period=delay, actions=[nav2]),
        ]
    )
