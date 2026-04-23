import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def generate_launch_description():

    pkg = get_package_share_directory('warehouse_robot_comp219')
    slam_config = os.path.join(pkg, 'config', 'slam_toolbox.yaml')

    slam = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        parameters=[slam_config, {'use_sim_time': True}],
        output='screen'
    )

    return LaunchDescription([slam])
