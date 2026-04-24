#include <cmath>
#include <chrono>
#include <iostream>
#include <limits>
#include <memory>
#include <string>
#include <vector>

#include "geometry_msgs/msg/pose_with_covariance_stamped.hpp"
#include "nav2_msgs/action/compute_path_to_pose.hpp"
#include "nav2_msgs/action/follow_path.hpp"
#include "nav2_msgs/action/navigate_to_pose.hpp"
#include "nav2_msgs/srv/manage_lifecycle_nodes.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"

using namespace std::chrono_literals;

class NavMenuClient : public rclcpp::Node
{
public:
  using NavigateToPose = nav2_msgs::action::NavigateToPose;
  using GoalHandleNavigateToPose = rclcpp_action::ClientGoalHandle<NavigateToPose>;
  using ComputePathToPose = nav2_msgs::action::ComputePathToPose;
  using GoalHandleComputePathToPose = rclcpp_action::ClientGoalHandle<ComputePathToPose>;
  using FollowPath = nav2_msgs::action::FollowPath;
  using GoalHandleFollowPath = rclcpp_action::ClientGoalHandle<FollowPath>;

  NavMenuClient()
  : Node("nav_menu_client")
  {
    navigate_client_ = rclcpp_action::create_client<NavigateToPose>(this, "navigate_to_pose");
    compute_path_client_ = rclcpp_action::create_client<ComputePathToPose>(this, "compute_path_to_pose");
    follow_path_client_ = rclcpp_action::create_client<FollowPath>(this, "follow_path");
    amcl_pose_sub_ = create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
      "/amcl_pose", 10, std::bind(&NavMenuClient::on_amcl_pose, this, std::placeholders::_1));

    nav_manager_client_ = create_client<nav2_msgs::srv::ManageLifecycleNodes>(
      "/lifecycle_manager_navigation/manage_nodes");
    loc_manager_client_ = create_client<nav2_msgs::srv::ManageLifecycleNodes>(
      "/lifecycle_manager_localization/manage_nodes");

    locations_ = {
      {"Loading Dock",     3.5, -3.0, 0.0},
      {"Dispatch Area",    3.5,  3.0, 1.5708},
      {"Charging Station", -3.5,  3.0, 1.5708},
      {"Inspection Point",  0.0,  0.0, 0.0},
    };
  }

  bool wait_for_nav2()
  {
    ensure_nav2_active();

    RCLCPP_INFO(
      get_logger(),
      "Waiting for Nav2 actions: /navigate_to_pose (or fallback: /compute_path_to_pose + /follow_path)");

    while (rclcpp::ok()) {
      const bool has_navigate = navigate_client_->wait_for_action_server(2s);
      if (has_navigate) {
        use_fallback_pipeline_ = false;
        RCLCPP_INFO(get_logger(), "Using /navigate_to_pose action.");
        return true;
      }

      const bool has_compute = compute_path_client_->wait_for_action_server(1s);
      const bool has_follow = follow_path_client_->wait_for_action_server(1s);
      if (has_compute && has_follow) {
        use_fallback_pipeline_ = true;
        RCLCPP_WARN(
          get_logger(),
          "/navigate_to_pose not available. Falling back to /compute_path_to_pose + /follow_path.");
        return true;
      }

      RCLCPP_WARN(
        get_logger(),
        "Still waiting... navigate_to_pose=%s, compute_path_to_pose=%s, follow_path=%s",
        has_navigate ? "up" : "down",
        has_compute ? "up" : "down",
        has_follow ? "up" : "down");
    }
    return false;
  }

  void run_menu()
  {
    while (rclcpp::ok()) {
      print_menu();
      const int choice = get_choice();

      if (choice == 0) {
        RCLCPP_INFO(get_logger(), "Exiting menu node.");
        break;
      }

      if (choice < 0 || choice > static_cast<int>(locations_.size())) {
        RCLCPP_WARN(get_logger(), "Invalid choice. Try again.");
        continue;
      }

      const auto & target = locations_[choice - 1];
      send_goal_and_wait(target);
    }
  }

private:
  struct Location
  {
    std::string name;
    double x;
    double y;
    double yaw;
  };

  rclcpp_action::Client<NavigateToPose>::SharedPtr navigate_client_;
  rclcpp_action::Client<ComputePathToPose>::SharedPtr compute_path_client_;
  rclcpp_action::Client<FollowPath>::SharedPtr follow_path_client_;
  rclcpp::Subscription<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr amcl_pose_sub_;
  rclcpp::Client<nav2_msgs::srv::ManageLifecycleNodes>::SharedPtr nav_manager_client_;
  rclcpp::Client<nav2_msgs::srv::ManageLifecycleNodes>::SharedPtr loc_manager_client_;
  std::vector<Location> locations_;
  bool use_fallback_pipeline_{false};
  bool have_amcl_pose_{false};
  geometry_msgs::msg::PoseStamped latest_start_pose_;

  bool call_manage_nodes(
    const rclcpp::Client<nav2_msgs::srv::ManageLifecycleNodes>::SharedPtr & client,
    uint8_t command,
    const std::string & label)
  {
    if (!client->wait_for_service(3s)) {
      RCLCPP_WARN(
        get_logger(),
        "Service %s/manage_nodes not available.",
        label.c_str());
      return false;
    }

    auto request = std::make_shared<nav2_msgs::srv::ManageLifecycleNodes::Request>();
    request->command = command;

    auto future = client->async_send_request(request);
    if (rclcpp::spin_until_future_complete(shared_from_this(), future, 20s) !=
      rclcpp::FutureReturnCode::SUCCESS)
    {
      RCLCPP_WARN(get_logger(), "%s manage_nodes call timed out.", label.c_str());
      return false;
    }

    const bool ok = future.get()->success;
    RCLCPP_INFO(
      get_logger(),
      "%s manage_nodes(cmd=%u) -> %s",
      label.c_str(), command, ok ? "success" : "failed");
    return ok;
  }

  bool ensure_nav2_active()
  {
    RCLCPP_INFO(get_logger(), "Ensuring Nav2 lifecycle is active...");
    const uint8_t STARTUP = nav2_msgs::srv::ManageLifecycleNodes::Request::STARTUP;
    const uint8_t RESUME = nav2_msgs::srv::ManageLifecycleNodes::Request::RESUME;

    // Try STARTUP first (brings unconfigured -> active). If that fails, the
    // nodes are likely already configured or active, so fall back to RESUME
    // (inactive -> active). Either success is treated as OK.
    bool loc_ok = call_manage_nodes(loc_manager_client_, STARTUP, "localization");
    if (!loc_ok) {
      loc_ok = call_manage_nodes(loc_manager_client_, RESUME, "localization");
    }
    bool nav_ok = call_manage_nodes(nav_manager_client_, STARTUP, "navigation");
    if (!nav_ok) {
      nav_ok = call_manage_nodes(nav_manager_client_, RESUME, "navigation");
    }
    return loc_ok || nav_ok;
  }

  void print_menu() const
  {
    std::cout << "\n========== Navigation Goal Menu ==========\n";
    for (size_t i = 0; i < locations_.size(); ++i) {
      std::cout << (i + 1) << ") " << locations_[i].name
                << "  [x=" << locations_[i].x
                << ", y=" << locations_[i].y << "]\n";
    }
    std::cout << "0) Exit\n";
    std::cout << "Select destination: ";
  }

  int get_choice() const
  {
    int choice = -1;
    std::cin >> choice;

    if (std::cin.eof()) {
      RCLCPP_INFO(rclcpp::get_logger("nav_menu_client"), "stdin closed; exiting.");
      rclcpp::shutdown();
      std::exit(0);
    }

    if (std::cin.fail()) {
      std::cin.clear();
      std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
      return -1;
    }
    return choice;
  }

  void send_goal_and_wait(const Location & location)
  {
    if (use_fallback_pipeline_) {
      send_goal_with_planner_controller(location);
      return;
    }

    NavigateToPose::Goal goal_msg;
    goal_msg.pose.header.frame_id = "map";
    goal_msg.pose.header.stamp = now();

    goal_msg.pose.pose.position.x = location.x;
    goal_msg.pose.pose.position.y = location.y;
    goal_msg.pose.pose.position.z = 0.0;

    goal_msg.pose.pose.orientation.x = 0.0;
    goal_msg.pose.pose.orientation.y = 0.0;
    goal_msg.pose.pose.orientation.z = std::sin(location.yaw * 0.5);
    goal_msg.pose.pose.orientation.w = std::cos(location.yaw * 0.5);

    RCLCPP_INFO(
      get_logger(),
      "Sending goal: %s (x=%.2f, y=%.2f, yaw=%.2f)",
      location.name.c_str(), location.x, location.y, location.yaw);

    auto goal_options = rclcpp_action::Client<NavigateToPose>::SendGoalOptions();
    auto goal_future = navigate_client_->async_send_goal(goal_msg, goal_options);

    if (rclcpp::spin_until_future_complete(shared_from_this(), goal_future) !=
      rclcpp::FutureReturnCode::SUCCESS)
    {
      RCLCPP_ERROR(get_logger(), "Failed to send goal.");
      return;
    }

    auto goal_handle = goal_future.get();
    if (!goal_handle) {
      RCLCPP_ERROR(get_logger(), "Goal was rejected by Nav2.");
      return;
    }

    RCLCPP_INFO(get_logger(), "Goal accepted. Waiting for result...");

    auto result_future = navigate_client_->async_get_result(goal_handle);
    if (rclcpp::spin_until_future_complete(shared_from_this(), result_future) !=
      rclcpp::FutureReturnCode::SUCCESS)
    {
      RCLCPP_ERROR(get_logger(), "Failed while waiting for goal result.");
      return;
    }

    auto wrapped_result = result_future.get();
    switch (wrapped_result.code) {
      case rclcpp_action::ResultCode::SUCCEEDED:
        RCLCPP_INFO(get_logger(), "Goal reached successfully.");
        break;
      case rclcpp_action::ResultCode::ABORTED:
        RCLCPP_ERROR(get_logger(), "Goal was aborted.");
        break;
      case rclcpp_action::ResultCode::CANCELED:
        RCLCPP_WARN(get_logger(), "Goal was canceled.");
        break;
      default:
        RCLCPP_ERROR(get_logger(), "Unknown result code from Nav2.");
        break;
    }
  }

  void send_goal_with_planner_controller(const Location & location)
  {
    ComputePathToPose::Goal compute_goal;
    compute_goal.goal.header.frame_id = "map";
    compute_goal.goal.header.stamp = now();
    compute_goal.goal.pose.position.x = location.x;
    compute_goal.goal.pose.position.y = location.y;
    compute_goal.goal.pose.position.z = 0.0;
    compute_goal.goal.pose.orientation.x = 0.0;
    compute_goal.goal.pose.orientation.y = 0.0;
    compute_goal.goal.pose.orientation.z = std::sin(location.yaw * 0.5);
    compute_goal.goal.pose.orientation.w = std::cos(location.yaw * 0.5);
    compute_goal.use_start = true;
    compute_goal.start = get_start_pose();

    RCLCPP_INFO(get_logger(), "Computing path to selected goal...");
    auto compute_goal_options = rclcpp_action::Client<ComputePathToPose>::SendGoalOptions();
    auto compute_goal_future = compute_path_client_->async_send_goal(compute_goal, compute_goal_options);

    if (rclcpp::spin_until_future_complete(shared_from_this(), compute_goal_future) !=
      rclcpp::FutureReturnCode::SUCCESS)
    {
      RCLCPP_ERROR(get_logger(), "Failed to send ComputePathToPose goal.");
      return;
    }

    auto compute_goal_handle = compute_goal_future.get();
    if (!compute_goal_handle) {
      RCLCPP_ERROR(get_logger(), "ComputePathToPose goal was rejected.");
      return;
    }

    auto compute_result_future = compute_path_client_->async_get_result(compute_goal_handle);
    if (rclcpp::spin_until_future_complete(shared_from_this(), compute_result_future) !=
      rclcpp::FutureReturnCode::SUCCESS)
    {
      RCLCPP_ERROR(get_logger(), "Failed while waiting for ComputePathToPose result.");
      return;
    }

    auto compute_result = compute_result_future.get();
    if (compute_result.code != rclcpp_action::ResultCode::SUCCEEDED) {
      RCLCPP_ERROR(get_logger(), "Path computation failed. Result code: %d", static_cast<int>(compute_result.code));
      return;
    }

    const auto & path = compute_result.result->path;
    if (path.poses.empty()) {
      RCLCPP_ERROR(get_logger(), "Planner returned an empty path.");
      return;
    }

    FollowPath::Goal follow_goal;
    follow_goal.path = path;

    RCLCPP_INFO(get_logger(), "Path computed. Executing FollowPath...");
    auto follow_goal_options = rclcpp_action::Client<FollowPath>::SendGoalOptions();
    auto follow_goal_future = follow_path_client_->async_send_goal(follow_goal, follow_goal_options);

    if (rclcpp::spin_until_future_complete(shared_from_this(), follow_goal_future) !=
      rclcpp::FutureReturnCode::SUCCESS)
    {
      RCLCPP_ERROR(get_logger(), "Failed to send FollowPath goal.");
      return;
    }

    auto follow_goal_handle = follow_goal_future.get();
    if (!follow_goal_handle) {
      RCLCPP_ERROR(
        get_logger(),
        "FollowPath goal was rejected. Controller likely inactive — attempting to re-activate Nav2...");
      if (ensure_nav2_active()) {
        RCLCPP_INFO(get_logger(), "Nav2 re-activated. Retrying FollowPath...");
        auto retry_future = follow_path_client_->async_send_goal(follow_goal, follow_goal_options);
        if (rclcpp::spin_until_future_complete(shared_from_this(), retry_future) !=
          rclcpp::FutureReturnCode::SUCCESS)
        {
          RCLCPP_ERROR(get_logger(), "Retry failed: could not send FollowPath goal.");
          return;
        }
        follow_goal_handle = retry_future.get();
        if (!follow_goal_handle) {
          RCLCPP_ERROR(get_logger(), "Retry failed: FollowPath still rejected.");
          return;
        }
      } else {
        return;
      }
    }

    auto follow_result_future = follow_path_client_->async_get_result(follow_goal_handle);
    if (rclcpp::spin_until_future_complete(shared_from_this(), follow_result_future) !=
      rclcpp::FutureReturnCode::SUCCESS)
    {
      RCLCPP_ERROR(get_logger(), "Failed while waiting for FollowPath result.");
      return;
    }

    auto follow_result = follow_result_future.get();
    switch (follow_result.code) {
      case rclcpp_action::ResultCode::SUCCEEDED:
        RCLCPP_INFO(get_logger(), "Goal reached successfully (planner+controller fallback).");
        break;
      case rclcpp_action::ResultCode::ABORTED:
        RCLCPP_ERROR(get_logger(), "FollowPath was aborted.");
        break;
      case rclcpp_action::ResultCode::CANCELED:
        RCLCPP_WARN(get_logger(), "FollowPath was canceled.");
        break;
      default:
        RCLCPP_ERROR(get_logger(), "Unknown FollowPath result code.");
        break;
    }
  }

  void on_amcl_pose(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg)
  {
    latest_start_pose_.header = msg->header;
    latest_start_pose_.pose = msg->pose.pose;
    have_amcl_pose_ = true;
  }

  geometry_msgs::msg::PoseStamped get_start_pose()
  {
    if (have_amcl_pose_) {
      latest_start_pose_.header.stamp = now();
      return latest_start_pose_;
    }

    geometry_msgs::msg::PoseStamped start;
    start.header.frame_id = "map";
    start.header.stamp = now();
    start.pose.position.x = -4.0;
    start.pose.position.y = -3.0;
    start.pose.position.z = 0.0;
    start.pose.orientation.w = 1.0;
    RCLCPP_WARN(get_logger(), "No /amcl_pose received yet; using default start (-4.0, -3.0).");
    return start;
  }
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);

  auto node = std::make_shared<NavMenuClient>();
  if (node->wait_for_nav2()) {
    node->run_menu();
  }

  rclcpp::shutdown();
  return 0;
}
