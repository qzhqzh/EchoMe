"""Run via Blender --background --factory-startup --python ... -- OUTPUT_DIR.

This is a reproducible technical probe for the whale-girl research question,
NOT the character deliverable or a substitute for the user's reference design.
It writes only into the explicitly supplied output directory.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("Pass an explicit, dedicated output directory after --")
    output = Path(args[0]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    def material(name: str, color: tuple) -> bpy.types.Material:
        value = bpy.data.materials.new(name)
        value.diffuse_color = color
        value.use_nodes = True
        shader = value.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = 0.48
        return value

    blue = material("Probe blue", (0.07, 0.31, 0.58, 1))
    pale = material("Probe underside", (0.55, 0.76, 0.86, 1))
    ground = material("Neutral backdrop", (0.025, 0.035, 0.06, 1))

    def ellipsoid(name: str, location: tuple, scale: tuple, mat: bpy.types.Material) -> None:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.scale = scale
        obj.data.materials.append(mat)
        for poly in obj.data.polygons:
            poly.use_smooth = True

    ellipsoid("WhaleVolume_technical_probe", (0, 0, 1.2), (1.7, 0.7, 0.75), blue)
    ellipsoid("Underside", (0.05, 0, 0.92), (1.35, 0.62, 0.45), pale)
    ellipsoid("Tail_base", (-1.65, 0, 1.28), (0.6, 0.3, 0.28), blue)
    ellipsoid("Fluke_left", (-2.05, -0.45, 1.34), (0.45, 0.65, 0.12), blue)
    ellipsoid("Fluke_right", (-2.05, 0.45, 1.34), (0.45, 0.65, 0.12), blue)
    ellipsoid("Fin_left", (0.15, -0.7, 0.95), (0.65, 0.45, 0.12), blue)
    ellipsoid("Fin_right", (0.15, 0.7, 0.95), (0.65, 0.45, 0.12), blue)
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0.08))
    bpy.context.object.name = "Ground"
    bpy.context.object.data.materials.append(ground)

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 12
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.2, 0.2, 0.2)
    for name, location, energy, size in [
        ("Key", (3, -4, 7), 1000, 5),
        ("Fill", (-3, 2, 5), 650, 4),
    ]:
        bpy.ops.object.light_add(type="AREA", location=location)
        obj = bpy.context.object
        obj.name = name
        obj.data.energy = energy
        obj.data.shape = "DISK"
        obj.data.size = size
        obj.rotation_euler = (Vector((0, 0, 1)) - obj.location).to_track_quat("-Z", "Y").to_euler()
    cameras = [("front", (6, -5, 3.3)), ("side", (0, -7, 2.7)), ("back", (-6, 4, 3.5))]
    for name, location in cameras:
        bpy.ops.object.camera_add(location=location)
        camera = bpy.context.object
        camera.name = "Preview_" + name
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = 6.6
        camera.rotation_euler = (
            (Vector((-0.3, 0, 1.1)) - camera.location).to_track_quat("-Z", "Y").to_euler()
        )
    scene.camera = bpy.data.objects["Preview_front"]
    blend_path = output / "whale-volume-probe.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    for name, _ in cameras:
        scene.camera = bpy.data.objects["Preview_" + name]
        scene.render.filepath = str(output / (name + ".png"))
        bpy.ops.render.render(write_still=True)
    # Reopen the saved file and inspect actual persisted data.
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    vertices = sum(len(obj.data.vertices) for obj in meshes)
    assert len(meshes) == 8 and vertices > 0
    assert all(math.isfinite(component) for obj in meshes for component in obj.dimensions)
    report = {
        "render_material_colors": {
            name: list(
                bpy.data.materials[name]
                .node_tree.nodes.get("Principled BSDF")
                .inputs["Base Color"]
                .default_value
            )
            for name in ("Probe blue", "Probe underside", "Neutral backdrop")
        },
        "case": "Whale-girl Blender pipeline technical probe",
        "scope": "Technical volume sample only; character reference and appearance acceptance are pending.",
        "blender_version": bpy.app.version_string,
        "saved_file_reopened": True,
        "mesh_objects": len(meshes),
        "vertices": vertices,
        "previews": [
            {"name": name + ".png", "size": (output / (name + ".png")).stat().st_size}
            for name, _ in cameras
        ],
        "checks": [
            "Saved .blend reopened",
            "Expected mesh count",
            "Finite dimensions",
            "Three rendered PNG files",
        ],
        "not_checked": ["Character likeness", "Rigging", "Animation", "Production topology"],
    }
    (output / "checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("ECHOME_PROBE_COMPLETE " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
