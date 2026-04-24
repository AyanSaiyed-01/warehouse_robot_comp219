import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():

    pkg = get_package_share_directory('warehouse_robot_comp219')

    world_file = os.path.join(pkg, 'worlds', 'warehouse.world')
    urdf_file  = os.path.join(pkg, 'urdf',   'warehouse_robot.urdf')

    with open(urdf_file, 'r') as f:
        robot_desc_str = f.read()

    robot_description = ParameterValue(robot_desc_str, value_type=str)

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
            '/world/warehouse/model/warehouse_robot/joint_state@sensor_msgs/msg/JointState[gz.msgs.Model',
        ],
        output='screen'
    )

    robot_state_publisher = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'robot_description': robot_description,
                     'use_sim_time': True}],
        output='screen'
    )

    joint_state_relay = Node(
        package='topic_tools',
        executable='relay',
        name='joint_state_relay',
        arguments=[
            '/world/warehouse/model/warehouse_robot/joint_state',
            '/joint_states'
        ],
        output='screen'
    )

    spawn_robot = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=[
            '-name',  'warehouse_robot',
            '-topic', 'robot_description',
            '-x', '-4.0',
            '-y', '-3.0',
            '-z', '0.1',
            '-Y', '0.0',
        ],
        output='screen'
    )

    # Dynamic odom -> base_footprint from /odom topic
    odom_tf = Node(
        package='warehouse_robot_comp219',
        executable='odom_tf_publisher.py',
        name='odom_tf_publisher',
        parameters=[{'use_sim_time': True}],
        output='screen'
    )

    return LaunchDescription([
        gazebo,
        bridge,
        robot_state_publisher,
        joint_state_relay,
        spawn_robot,
        odom_tf,
    ])
