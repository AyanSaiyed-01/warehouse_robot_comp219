#!/usr/bin/env python3
"""AI agent that drives the warehouse robot from natural-language commands.

Architecture
------------
* Uses LangChain's tool-calling agent (Gemini backend by default).
* Exposes the robot's navigation capabilities as LangChain tools.
* Each tool does one thing (navigate, list, cancel, status) and wraps the
  Nav2 ``NavigateToPose`` action via rclpy.
* If ``GOOGLE_API_KEY`` is not set, falls back to a deterministic keyword
  matcher so the demo still works offline.

Run
---
    export GOOGLE_API_KEY=...        # optional, for the real LLM
    ros2 run warehouse_robot_comp219 ai_nav_client.py
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import ComputePathToPose, FollowPath, NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node


# ---------------------------------------------------------------------------
# Known warehouse destinations. Keep these in sync with src/nav_menu.cpp.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Location:
    name: str
    x: float
    y: float
    yaw: float = 0.0
    aliases: tuple = ()


LOCATIONS: List[Location] = [
    Location(
        "Loading Dock",
        3.5,
        -3.0,
        0.0,
        aliases=("loading", "dock", "pickup", "load zone", "receiving"),
    ),
    Location(
        "Dispatch Area",
        3.5,
        3.0,
        0.0,
        aliases=("dispatch", "shipping", "outbound", "delivery", "send off"),
    ),
    Location(
        "Charging Station",
        -3.5,
        3.0,
        0.0,
        aliases=("charging", "charger", "recharge", "battery", "power"),
    ),
    Location(
        "Inspection Point",
        0.0,
        0.0,
        0.0,
        aliases=("inspection", "inspect", "qc", "quality", "check", "middle", "center"),
    ),
]


def match_location(query: str) -> Optional[Location]:
    """Fuzzy-match a user query to one of the known warehouse locations."""
    q = query.strip().lower()
    if not q:
        return None

    for loc in LOCATIONS:
        if loc.name.lower() == q:
            return loc

    for loc in LOCATIONS:
        if loc.name.lower() in q or q in loc.name.lower():
            return loc
        for alias in loc.aliases:
            if alias in q:
                return loc
    return None


# ---------------------------------------------------------------------------
# ROS wrapper: owns the rclpy node and the NavigateToPose action client.
# ---------------------------------------------------------------------------
class NavBridge(Node):
    def __init__(self) -> None:
        super().__init__("ai_nav_client")
        self._action = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self._compute_client = ActionClient(self, ComputePathToPose, "compute_path_to_pose")
        self._follow_client = ActionClient(self, FollowPath, "follow_path")
        self._amcl_sub = self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self._on_amcl_pose,
            10,
        )
        self._current_goal_handle = None
        self._latest_amcl: Optional[PoseWithCovarianceStamped] = None
        self._status_text = "idle"
        self._lock = threading.Lock()

    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped) -> None:
        self._latest_amcl = msg

    def wait_for_nav2(self, timeout_s: float = 20.0) -> bool:
        self.get_logger().info("Waiting for /navigate_to_pose action server...")
        return self._action.wait_for_server(timeout_sec=timeout_s)

    def current_pose_text(self) -> str:
        if self._latest_amcl is None:
            return "unknown (robot has not localized yet)"
        p = self._latest_amcl.pose.pose.position
        return f"x={p.x:.2f}, y={p.y:.2f} in map frame"

    def status(self) -> str:
        with self._lock:
            return self._status_text

    def cancel(self) -> str:
        with self._lock:
            handle = self._current_goal_handle
            self._current_goal_handle = None
        if handle is None:
            return "No active navigation goal to cancel."
        future = handle.cancel_goal_async()
        rclpy.spin_until_future_complete(self, future, timeout_sec=5.0)
        self._status_text = "cancelled"
        return "Cancel request sent to Nav2."

    def _make_pose(self, location: Location):
        from geometry_msgs.msg import PoseStamped

        p = PoseStamped()
        p.header.frame_id = "map"
        p.header.stamp = self.get_clock().now().to_msg()
        p.pose.position.x = location.x
        p.pose.position.y = location.y
        p.pose.position.z = 0.0
        p.pose.orientation.z = math.sin(location.yaw / 2.0)
        p.pose.orientation.w = math.cos(location.yaw / 2.0)
        return p

    def navigate(self, location: Location, timeout_s: float = 180.0) -> str:
        if self._action.wait_for_server(timeout_sec=1.5):
            return self._navigate_to_pose(location, timeout_s)
        return self._navigate_via_planner(location, timeout_s)

    def _navigate_to_pose(self, location: Location, timeout_s: float) -> str:
        goal = NavigateToPose.Goal()
        goal.pose = self._make_pose(location)

        self._status_text = f"sending goal to {location.name}"
        send_future = self._action.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=5.0)
        goal_handle = send_future.result()
        if goal_handle is None or not goal_handle.accepted:
            self._status_text = "goal rejected (trying fallback)"
            return self._navigate_via_planner(location, timeout_s)

        with self._lock:
            self._current_goal_handle = goal_handle
        self._status_text = f"navigating to {location.name}"

        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=timeout_s)
        with self._lock:
            self._current_goal_handle = None

        if not result_future.done():
            self._status_text = "timed out"
            return f"Navigation to {location.name} timed out after {timeout_s:.0f}s."

        result = result_future.result()
        code = result.status
        if code == 4:
            self._status_text = f"arrived at {location.name}"
            return f"Arrived at {location.name} (x={location.x}, y={location.y})."
        if code == 5:
            self._status_text = "cancelled"
            return f"Navigation to {location.name} was cancelled."
        if code == 6:
            self._status_text = "aborted"
            return (
                f"Navigation to {location.name} was aborted by Nav2. "
                "The robot may be stuck or the goal may be unreachable."
            )
        self._status_text = f"unknown (code {code})"
        return f"Navigation ended with status code {code}."

    def _navigate_via_planner(self, location: Location, timeout_s: float) -> str:
        """Fallback: ComputePathToPose + FollowPath (same as nav_menu C++ client)."""
        if not self._compute_client.wait_for_server(timeout_sec=5.0):
            self._status_text = "planner unavailable"
            return "Planner action server not available."
        if not self._follow_client.wait_for_server(timeout_sec=5.0):
            self._status_text = "controller unavailable"
            return "Controller action server not available."

        self._status_text = f"planning path to {location.name}"
        compute_goal = ComputePathToPose.Goal()
        compute_goal.goal = self._make_pose(location)
        compute_goal.use_start = False

        cf = self._compute_client.send_goal_async(compute_goal)
        rclpy.spin_until_future_complete(self, cf, timeout_sec=5.0)
        c_handle = cf.result()
        if c_handle is None or not c_handle.accepted:
            self._status_text = "plan rejected"
            return f"Planner rejected goal to {location.name}."

        cr = c_handle.get_result_async()
        rclpy.spin_until_future_complete(self, cr, timeout_sec=15.0)
        if not cr.done():
            self._status_text = "plan timed out"
            return f"Planner timed out computing path to {location.name}."
        plan_result = cr.result()
        if plan_result.status != 4 or not plan_result.result.path.poses:
            self._status_text = "no path"
            return f"Planner could not find a path to {location.name}."

        self._status_text = f"following path to {location.name}"
        follow_goal = FollowPath.Goal()
        follow_goal.path = plan_result.result.path

        ff = self._follow_client.send_goal_async(follow_goal)
        rclpy.spin_until_future_complete(self, ff, timeout_sec=5.0)
        f_handle = ff.result()
        if f_handle is None or not f_handle.accepted:
            self._status_text = "follow rejected"
            return f"Controller rejected the path to {location.name}."

        with self._lock:
            self._current_goal_handle = f_handle

        fr = f_handle.get_result_async()
        rclpy.spin_until_future_complete(self, fr, timeout_sec=timeout_s)
        with self._lock:
            self._current_goal_handle = None

        if not fr.done():
            self._status_text = "timed out"
            return f"Navigation to {location.name} timed out after {timeout_s:.0f}s."

        code = fr.result().status
        if code == 4:
            self._status_text = f"arrived at {location.name}"
            return f"Arrived at {location.name} (x={location.x}, y={location.y})."
        if code == 5:
            self._status_text = "cancelled"
            return f"Navigation to {location.name} was cancelled."
        if code == 6:
            self._status_text = "aborted"
            return (
                f"Navigation to {location.name} was aborted. "
                "The robot may be stuck or the path may be invalid."
            )
        self._status_text = f"unknown (code {code})"
        return f"Navigation ended with status code {code}."


# ---------------------------------------------------------------------------
# LangChain tools. Bound to a NavBridge instance via the ``bind`` helper.
# ---------------------------------------------------------------------------
def build_langchain_tools(bridge: NavBridge):
    """Return (tools, agent_prompt_system_msg) for the LangChain agent.

    Imports are local so users without LangChain installed can still run the
    offline fallback path.
    """
    from langchain_core.tools import tool

    @tool
    def list_locations() -> str:
        """List every named destination the robot can navigate to."""
        lines = [f"- {loc.name} (x={loc.x}, y={loc.y})" for loc in LOCATIONS]
        return "Known warehouse destinations:\n" + "\n".join(lines)

    @tool
    def get_current_pose() -> str:
        """Return the robot's current pose in the map frame as reported by AMCL."""
        return bridge.current_pose_text()

    @tool
    def get_navigation_status() -> str:
        """Return what the robot is doing right now: idle, navigating, arrived, etc."""
        return bridge.status()

    @tool
    def navigate_to_location(location: str) -> str:
        """Drive the robot to one of the known warehouse destinations.

        ``location`` must match (case insensitive, fuzzy) one of: Loading Dock,
        Dispatch Area, Charging Station, Inspection Point.

        Blocks until the robot arrives, is cancelled, aborts, or times out,
        then returns a human-readable status.
        """
        loc = match_location(location)
        if loc is None:
            names = ", ".join(l.name for l in LOCATIONS)
            return (
                f"Unknown location '{location}'. Please pick one of: {names}."
            )
        return bridge.navigate(loc)

    @tool
    def cancel_current_navigation() -> str:
        """Cancel any in-progress navigation goal."""
        return bridge.cancel()

    tools = [
        list_locations,
        get_current_pose,
        get_navigation_status,
        navigate_to_location,
        cancel_current_navigation,
    ]

    system_msg = (
        "You are the dispatcher for a mobile warehouse robot. The user speaks "
        "to you in natural language and you must decide which tool to call to "
        "satisfy the request. Always prefer calling a tool over guessing. "
        "After a tool returns, summarize the outcome in one short sentence. "
        "If the user asks for a location that is not in the known list, ask "
        "them to rephrase using one of the known destinations. Never invent "
        "coordinates or locations that weren't returned by list_locations."
    )
    return tools, system_msg


# ---------------------------------------------------------------------------
# LangChain agent wrapper.
# ---------------------------------------------------------------------------
class LangChainAgent:
    """LangChain 1.x agent using ``langchain.agents.create_agent``.

    The agent maintains a running chat history so the LLM can reason across
    follow-up messages ('go there again', 'now cancel that', etc.).
    """

    def __init__(
        self,
        bridge: NavBridge,
        provider: str = "gemini",
        model: Optional[str] = None,
    ) -> None:
        # Imports are deferred so the offline fallback path stays importable.
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI
        from langchain_google_genai import (  # type: ignore[reportMissingImports]
            ChatGoogleGenerativeAI,
        )

        self._bridge = bridge
        tools, system_msg = build_langchain_tools(bridge)
        provider_name = provider.strip().lower()
        if provider_name == "gemini":
            llm = ChatGoogleGenerativeAI(
                model=model or "gemini-2.5-flash",
                temperature=0.0,
            )
        elif provider_name == "openai":
            llm = ChatOpenAI(
                model=model or "gpt-4o-mini",
                temperature=0.0,
            )
        else:
            raise ValueError(
                f"Unsupported LLM provider '{provider}'. Use 'gemini' or 'openai'."
            )
        self._agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=system_msg,
        )
        self._history: list = []

    def chat(self, user_input: str) -> str:
        self._history.append({"role": "user", "content": user_input})
        result = self._agent.invoke({"messages": self._history})
        messages = result.get("messages", [])
        if not messages:
            return ""
        final = messages[-1]
        self._history = list(messages)
        content = getattr(final, "content", None)
        if content is None and isinstance(final, dict):
            content = final.get("content", "")
        return str(content).strip()


# ---------------------------------------------------------------------------
# Offline fallback agent (no API key / no LangChain).
# ---------------------------------------------------------------------------
class OfflineAgent:
    """Minimal deterministic agent: keyword-matches destinations."""

    def __init__(self, bridge: NavBridge) -> None:
        self._bridge = bridge

    def chat(self, user_input: str) -> str:
        q = user_input.lower().strip()

        if any(k in q for k in ("cancel", "stop", "halt")):
            return self._bridge.cancel()

        # Pose query before the generic "list" branch so "where are you" wins.
        if any(k in q for k in ("pose", "where are you", "your location", "your position")):
            return "Current pose: " + self._bridge.current_pose_text()

        if any(k in q for k in ("status", "what are you doing", "state")):
            return f"Status: {self._bridge.status()}"

        if any(k in q for k in ("list", "destinations", "options", "menu", "choices")):
            names = "\n".join(
                f"- {loc.name} (x={loc.x}, y={loc.y})" for loc in LOCATIONS
            )
            return "Known warehouse destinations:\n" + names

        loc = match_location(q)
        if loc is not None:
            return self._bridge.navigate(loc)

        return (
            "I couldn't parse that. Try something like 'go to the loading dock' "
            "or 'list locations'."
        )


# ---------------------------------------------------------------------------
# Interactive terminal loop.
# ---------------------------------------------------------------------------
BANNER = """
==========================================================
   AI Navigation Agent for warehouse_robot_comp219
==========================================================
Type natural-language commands, for example:
  - take the robot to the loading dock
  - where are you right now?
  - cancel the current job
  - list every destination you know
Type 'exit' or press Ctrl+D to quit.
"""


def run_repl(bridge: NavBridge, agent) -> None:
    print(BANNER)
    while rclpy.ok():
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            return
        try:
            reply = agent.chat(user_input)
        except Exception as exc:  # noqa: BLE001 - we want to surface any failure
            reply = f"Agent error: {exc}"
        print(f"bot> {reply}\n")


def build_agent(bridge: NavBridge):
    """Pick LangChain LLM backend from env vars, else offline fallback."""
    provider = os.environ.get("AI_NAV_PROVIDER", "gemini").strip().lower()

    has_gemini_key = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))

    if provider == "gemini" and not has_gemini_key:
        print(
            "[ai_nav_client] GOOGLE_API_KEY is not set; using offline keyword "
            "matcher. Set GOOGLE_API_KEY (or GEMINI_API_KEY) to enable Gemini.",
            file=sys.stderr,
        )
        return OfflineAgent(bridge)
    if provider == "openai" and not has_openai_key:
        print(
            "[ai_nav_client] OPENAI_API_KEY is not set; using offline keyword "
            "matcher. Set OPENAI_API_KEY to enable OpenAI.",
            file=sys.stderr,
        )
        return OfflineAgent(bridge)
    if provider not in {"gemini", "openai"}:
        print(
            f"[ai_nav_client] Unknown AI_NAV_PROVIDER='{provider}'. "
            "Use 'gemini' or 'openai'. Falling back to offline matcher.",
            file=sys.stderr,
        )
        return OfflineAgent(bridge)

    try:
        model_env = "GEMINI_MODEL" if provider == "gemini" else "OPENAI_MODEL"
        return LangChainAgent(
            bridge,
            provider=provider,
            model=os.environ.get(model_env),
        )
    except ImportError as exc:
        print(
            f"[ai_nav_client] LangChain import failed ({exc}); falling back "
            "to offline keyword matcher. Install dependencies with:\n"
            "    pip install langchain langchain-openai langchain-google-genai",
            file=sys.stderr,
        )
        return OfflineAgent(bridge)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[ai_nav_client] Failed to initialize {provider} backend ({exc}); "
            "falling back to offline keyword matcher.",
            file=sys.stderr,
        )
        return OfflineAgent(bridge)


def main() -> None:
    rclpy.init()
    bridge = NavBridge()

    # Spin ROS callbacks in a background thread so /amcl_pose keeps updating.
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(bridge)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        if not bridge.wait_for_nav2(timeout_s=15.0):
            print(
                "[ai_nav_client] WARNING: /navigate_to_pose action not "
                "available. Is Nav2 running?",
                file=sys.stderr,
            )
        # Give AMCL a moment so the first status queries aren't "unknown".
        time.sleep(1.0)

        agent = build_agent(bridge)
        run_repl(bridge, agent)
    finally:
        executor.shutdown()
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
