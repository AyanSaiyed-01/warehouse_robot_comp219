cmake_minimum_required(VERSION 3.8)
project(warehouse_robot_comp219)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)

add_executable(nav_menu_client src/nav_menu.cpp)
ament_target_dependencies(nav_menu_client
  rclcpp
  rclcpp_action
  nav2_msgs
  geometry_msgs
)

install(DIRECTORY worlds urdf launch config maps
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  warehouse_robot_comp219/odom_tf_publisher.py
  DESTINATION lib/${PROJECT_NAME}
)

install(TARGETS
  nav_menu_client
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
