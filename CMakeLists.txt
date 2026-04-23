cmake_minimum_required(VERSION 3.8)
project(warehouse_robot_comp219)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)

install(DIRECTORY worlds urdf launch config maps
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  warehouse_robot_comp219/odom_tf_publisher.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
