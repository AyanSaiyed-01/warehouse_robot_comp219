import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, TimerAction
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('warehouse_robot_comp219')

    world_file = os.path.join(pkg, 'worlds', 'warehouse.world')
    urdf_file = os.path.join(pkg, 'urdf', 'warehouse_robot.urdf')
    urdf_content = Path(urdf_file).read_text(encoding='utf-8')

    use_sim_time = {'use_sim_time': True}

    gazebo = ExecuteProcess(
        cmd=['gz', 'sim', '-r', world_file],
        output='screen'
    )

    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        arguments=[
            '/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan',
            '/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry',
            '/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',
            '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',
        ],
        parameters=[use_sim_time],
        output='screen'
    )

    spawn_robot = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=[
            '-name', 'warehouse_robot',
            '-file', urdf_file,
            '-x', '-4.0',
            '-y', '-3.0',
            '-z', '0.1',
            '-Y', '0.0',
        ],
        parameters=[use_sim_time],
        output='screen'
    )

    odom_tf = Node(
        package='warehouse_robot_comp219',
        executable='odom_tf_publisher.py',
        name='odom_tf_publisher',
        parameters=[use_sim_time],
        output='screen'
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[
            use_sim_time,
            {'robot_description': urdf_content},
        ],
    )

    joint_state_publisher = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        output='screen',
        parameters=[
            use_sim_time,
            {'robot_description': urdf_content},
        ],
    )

    return LaunchDescription(
        [
            gazebo,
            bridge,
            # Let gz sim finish loading the world so /create places the model at
            # the intended pose in world coordinates.
            TimerAction(period=4.0, actions=[spawn_robot]),
            odom_tf,
            robot_state_publisher,
            joint_state_publisher,
        ]
    )
