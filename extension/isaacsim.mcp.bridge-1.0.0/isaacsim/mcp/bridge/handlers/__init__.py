"""
Handler package — re-exports all handler functions.

Extension.py imports from `.handlers`, so this facade ensures
the existing import statement continues to work unchanged.
"""

# --- Camera & viewport ---
from .camera import (
    handle_camera_inspect,
    handle_camera_look_at,
    handle_camera_set,
    handle_capture,
    handle_viewport_light,
)

# --- Logging ---
from .logging import handle_get_logs

# --- Misc (health, execute, debug, extensions) ---
from .misc import (
    handle_draw_debug,
    handle_execute,
    handle_extensions_list,
    handle_extensions_manage,
    handle_health,
)

# --- Recording ---
from .recording import (
    handle_recording_frame,
    handle_recording_start,
    handle_recording_stop,
)

# --- Robot ---
from .robot import (
    handle_create_robot,
    handle_get_joint_states,
    handle_get_robot_info,
    handle_set_joint_targets,
)

# --- Scene ---
from .scene import (
    handle_clone_prim,
    handle_create_prim,
    handle_delete_prim,
    handle_face_count_tree,
    handle_mesh_stats,
    handle_new_scene,
    handle_prim_bounds,
    handle_prim_properties,
    handle_save_scene,
    handle_scene_dump,
    handle_scene_tree,
    handle_set_material,
    handle_set_visibility,
    handle_transform,
)

# --- Simulation & physics ---
from .simulation import (
    handle_apply_force,
    handle_raycast,
    handle_set_physics_properties,
    handle_sim_control,
    handle_sim_state,
)

# --- USD advanced (flatten, export, variants, compare, material paths) ---
from .usd_advanced import (
    handle_compare_prims,
    handle_create_variant_structure,
    handle_export_prim,
    handle_flatten_usd,
    handle_set_variant_selection,
    handle_update_material_paths,
)

# Re-export _compute_world_bbox for formatter.py backwards compatibility
from ._utils import _compute_world_bbox

__all__ = [
    # Camera
    "handle_camera_inspect",
    "handle_camera_look_at",
    "handle_camera_set",
    "handle_capture",
    "handle_viewport_light",
    # Logging
    "handle_get_logs",
    # Misc
    "handle_draw_debug",
    "handle_execute",
    "handle_extensions_list",
    "handle_extensions_manage",
    "handle_health",
    # Recording
    "handle_recording_frame",
    "handle_recording_start",
    "handle_recording_stop",
    # Robot
    "handle_create_robot",
    "handle_get_joint_states",
    "handle_get_robot_info",
    "handle_set_joint_targets",
    # Scene
    "handle_clone_prim",
    "handle_create_prim",
    "handle_delete_prim",
    "handle_face_count_tree",
    "handle_mesh_stats",
    "handle_new_scene",
    "handle_prim_bounds",
    "handle_prim_properties",
    "handle_save_scene",
    "handle_scene_dump",
    "handle_scene_tree",
    "handle_set_material",
    "handle_set_visibility",
    "handle_transform",
    # Simulation
    "handle_apply_force",
    "handle_raycast",
    "handle_set_physics_properties",
    "handle_sim_control",
    "handle_sim_state",
    # USD advanced
    "handle_compare_prims",
    "handle_create_variant_structure",
    "handle_export_prim",
    "handle_flatten_usd",
    "handle_set_variant_selection",
    "handle_update_material_paths",
    # Utils (for formatter.py)
    "_compute_world_bbox",
]
