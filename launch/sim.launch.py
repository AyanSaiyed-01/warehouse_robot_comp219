import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node


def generate_launch_description():
    pkg = get_package_share_directory('warehouse_robot_comp219')

    world_file = os.path.join(pkg, 'worlds', 'warehouse.world')
    urdf_file = os.path.join(pkg, 'urdf', 'warehouse_robot.urdf')

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

    # /odom topic -> TF (odom -> base_footprint). Required by Nav2's
    # local costmap / controller_server. Uses node clock which is sim time
    # because use_sim_time=True.
    odom_tf = Node(
        package='warehouse_robot_comp219',
        executable='odom_tf_publisher.py',
        name='odom_tf_publisher',
        parameters=[use_sim_time],
        output='screen'
    )

    # Robot-internal fixed transforms. robot_state_publisher is not used here
    # because we spawn the URDF directly via ros_gz_sim create; these mirror
    # the fixed joints (base_footprint_joint) and lidar mounting in the URDF.
    base_footprint_to_base_link = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_footprint_to_base_link',
        arguments=['0', '0', '0.06', '0', '0', '0', 'base_footprint', 'base_link'],
        parameters=[use_sim_time],
        output='screen'
    )

    base_link_to_lidar = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_link_to_lidar',
        arguments=['0', '0', '0.12', '0', '0', '0', 'base_link', 'lidar_link'],
        parameters=[use_sim_time],
        output='screen'
    )

    return LaunchDescription([
        gazebo,
        bridge,
        spawn_robot,
        odom_tf,
        base_footprint_to_base_link,
        base_link_to_lidar,
    ])
