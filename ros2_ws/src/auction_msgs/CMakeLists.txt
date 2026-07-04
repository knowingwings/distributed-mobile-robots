cmake_minimum_required(VERSION 3.8)
project(auction_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/PriceEntry.msg"
  "msg/PriceTable.msg"
  "msg/RoundGossip.msg"
  "msg/RecruitAnnouncement.msg"
  "msg/Heartbeat.msg"
  "msg/RoundAnnouncement.msg"
  "msg/LeaseRenewal.msg"
  "msg/TaskCompleted.msg"
  "msg/TaskSpec.msg"
  "msg/TaskArray.msg"
)

ament_package()
