import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory("warehouse_robot_comp219")
    nav2_pkg = get_package_share_directory("nav2_bringup")

    map_file = LaunchConfiguration("map")
    params_file = LaunchConfiguration("params_file")
    use_sim_time = LaunchConfiguration("use_sim_time")
    autostart = LaunchConfiguration("autostart")

    declare_map = DeclareLaunchArgument(
        "map",
        default_value=os.path.join(pkg, "maps", "warehouse_map.yaml"),
        description="Full path to map yaml file",
    )

    declare_params_file = DeclareLaunchArgument(
        "params_file",
        default_value=os.path.join(pkg, "config", "nav2_params.yaml"),
        description="Full path to Nav2 params file",
    )

    declare_use_sim_time = DeclareLaunchArgument(
        "use_sim_time",
        default_value="true",
        description="Use simulation clock if true",
    )

    declare_autostart = DeclareLaunchArgument(
        "autostart",
        default_value="true",
        description="Automatically startup nav2",
    )

    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_pkg, "launch", "localization_launch.py")
        ),
        launch_arguments={
            "map": map_file,
            "params_file": params_file,
            "use_sim_time": use_sim_time,
            "autostart": autostart,
            "use_composition": "False",
            "use_respawn": "False",
        }.items(),
    )

    planner_server = Node(
        package="nav2_planner",
        executable="planner_server",
        name="planner_server",
        output="screen",
        parameters=[params_file, {"use_sim_time": use_sim_time}],
    )

    controller_server = Node(
        package="nav2_controller",
        executable="controller_server",
        name="controller_server",
        output="screen",
        parameters=[params_file, {"use_sim_time": use_sim_time}],
    )

    smoother_server = Node(
        package="nav2_smoother",
        executable="smoother_server",
        name="smoother_server",
        output="screen",
        parameters=[params_file, {"use_sim_time": use_sim_time}],
    )

    behavior_server = Node(
        package="nav2_behaviors",
        executable="behavior_server",
        name="behavior_server",
        output="screen",
        parameters=[params_file, {"use_sim_time": use_sim_time}],
    )

    waypoint_follower = Node(
        package="nav2_waypoint_follower",
        executable="waypoint_follower",
        name="waypoint_follower",
        output="screen",
        parameters=[params_file, {"use_sim_time": use_sim_time}],
    )

    lifecycle_manager_navigation = Node(
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_navigation",
        output="screen",
        parameters=[
            {"use_sim_time": use_sim_time},
            {"autostart": autostart},
            {
                "node_names": [
                    "controller_server",
                    "planner_server",
                    "smoother_server",
                    "behavior_server",
                    "waypoint_follower",
                ]
            },
        ],
    )

    return LaunchDescription([
        declare_map,
        declare_params_file,
        declare_use_sim_time,
        declare_autostart,
        localization,
        planner_server,
        controller_server,
        smoother_server,
        behavior_server,
        waypoint_follower,
        lifecycle_manager_navigation,
    ])
