bl_info = {
    "name": "Voxelizer",
    "author": "The French Monkey",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Voxelizer",
    "description": "Turn objects into voxels using universal voxel grid resolution",
    "category": "3D View",
    "license": "GPL-3.0-or-later",
}

import bpy
import bmesh
import math
from mathutils import Matrix, Vector
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import IntProperty, PointerProperty
from mathutils.bvhtree import BVHTree

# ------------------------------------------------------------------------
# Universal Grid System
# ------------------------------------------------------------------------

def get_voxel_size(level):
    return 1.0 / (2 ** (level - 1))

def snap_to_grid(coord, voxel_size):
    return round(coord / voxel_size) * voxel_size

def snap_vector_to_grid(vec, voxel_size):
    return Vector((
        snap_to_grid(vec.x, voxel_size),
        snap_to_grid(vec.y, voxel_size),
        snap_to_grid(vec.z, voxel_size),
    ))

# ------------------------------------------------------------------------
# Source Collection Management
# ------------------------------------------------------------------------

def get_or_create_source(obj, context):
    for child in obj.children:
        if child.get("voxel_source") and child.data and len(child.data.vertices) > 0:
            if not obj.get("is_voxelized"):
                bpy.data.objects.remove(child, do_unlink=True)
                break
            else:
                return child

    source_mesh = obj.data.copy()
    source = bpy.data.objects.new(f"{obj.name}_VoxelSource", source_mesh)
    source["voxel_source"] = True
    source.hide_viewport = True
    source.hide_render = True
    source.hide_select = True
    source.display_type = 'WIRE'

    parent_collection = obj.users_collection[0] if obj.users_collection else context.scene.collection
    parent_collection.objects.link(source)

    source.parent = obj
    source.matrix_parent_inverse = obj.matrix_world.inverted()

    return source

# ------------------------------------------------------------------------
# Core Voxelization
# ------------------------------------------------------------------------

def voxelizer_object(obj, context, grid_level):
    if obj.type != "MESH":
        return

    voxel_size = get_voxel_size(grid_level)
    half = voxel_size / 2.0
    inflate_margin = half * 1.05
    epsilon = voxel_size * 0.02

    source = get_or_create_source(obj, context)
    depsgraph = context.evaluated_depsgraph_get()
    eval_source = source.evaluated_get(depsgraph)

    mesh_eval = eval_source.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    mesh_eval.transform(eval_source.matrix_world)  

    bm = bmesh.new()
    bm.from_mesh(mesh_eval)
    bvh = BVHTree.FromBMesh(bm)

    verts = [v.co.copy() for v in bm.verts]
    if not verts:
        bm.free()
        eval_source.to_mesh_clear()
        return

    min_corner = Vector((min(v.x for v in verts),
                         min(v.y for v in verts),
                         min(v.z for v in verts)))
    max_corner = Vector((max(v.x for v in verts),
                         max(v.y for v in verts),
                         max(v.z for v in verts)))
    bbox_center = (min_corner + max_corner) * 0.5
    bbox_size = max_corner - min_corner

    num_x = math.ceil(bbox_size.x / voxel_size) + 2
    num_y = math.ceil(bbox_size.y / voxel_size) + 2
    num_z = math.ceil(bbox_size.z / voxel_size) + 2

    grid_size = Vector((num_x * voxel_size, num_y * voxel_size, num_z * voxel_size))
    grid_origin = bbox_center - (grid_size * 0.5)

    occupied_voxels = []
    search_radius = half * math.sqrt(3) + epsilon

    for ix in range(num_x):
        for iy in range(num_y):
            for iz in range(num_z):
                center = grid_origin + Vector((
                    (ix + 0.5) * voxel_size,
                    (iy + 0.5) * voxel_size,
                    (iz + 0.5) * voxel_size))

                hits = bvh.find_nearest_range(center, search_radius)
                if hits:
                    occupied_voxels.append(center)
                    continue

                nearest = bvh.find_nearest(center)
                if nearest and nearest[3] <= inflate_margin:
                    occupied_voxels.append(center)

    bm.free()
    eval_source.to_mesh_clear()

    if not occupied_voxels:
        occupied_voxels = [bbox_center]

    voxels_rel = [v - bbox_center for v in occupied_voxels]
    voxel_mesh = create_instanced_voxel_mesh(obj, voxels_rel, voxel_size, context)

    verts = [v.co.copy() for v in voxel_mesh.vertices]
    min_voxel_corner = Vector((
        min(v.x for v in verts),
        min(v.y for v in verts),
        min(v.z for v in verts),
    ))

    for v in voxel_mesh.vertices:
        v.co -= min_voxel_corner
    voxel_mesh.update()

    old_mesh = obj.data
    voxel_mesh.materials.clear()
    for mat in old_mesh.materials:
        voxel_mesh.materials.append(mat)

    obj.data = voxel_mesh

    prev_loc = obj.location.copy()
    snapped_loc = Vector((
        round(prev_loc.x / voxel_size) * voxel_size,
        round(prev_loc.y / voxel_size) * voxel_size,
        round(prev_loc.z / voxel_size) * voxel_size,
    ))

    obj.location = snapped_loc
    obj["is_voxelized"] = True

    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)

    context.view_layer.update()

def create_instanced_voxel_mesh(obj, voxel_positions, voxel_size, context):
    import bmesh

    mesh = bpy.data.meshes.new("VoxelPoints")
    bm = bmesh.new()
    for pos in voxel_positions:
        bm.verts.new(pos)
    bm.to_mesh(mesh)
    bm.free()

    temp_obj = bpy.data.objects.new("VoxelTemp", mesh)
    context.scene.collection.objects.link(temp_obj)

    node_group = get_voxel_instancer_node_group(voxel_size)
    geo_mod = temp_obj.modifiers.new("VoxelInstances", 'NODES')
    geo_mod.node_group = node_group

    depsgraph = context.evaluated_depsgraph_get()
    temp_eval = temp_obj.evaluated_get(depsgraph)
    final_mesh = bpy.data.meshes.new_from_object(temp_eval, depsgraph=depsgraph)
    final_mesh.name = "VoxelMesh"

    bm_final = bmesh.new()
    bm_final.from_mesh(final_mesh)
    uv_layer = bm_final.loops.layers.uv.new("UVMap")

    verts = [v.co for v in bm_final.verts]
    min_x = min(v.x for v in verts)
    max_x = max(v.x for v in verts)
    min_y = min(v.y for v in verts)
    max_y = max(v.y for v in verts)

    num_x = max(1, round((max_x - min_x) / voxel_size))
    num_y = max(1, round((max_y - min_y) / voxel_size))

    tile_u = 1.0 / num_x
    tile_v = 1.0 / num_y

    for face in bm_final.faces:
        center = face.calc_center_median()
        ix = int((center.x - min_x) / voxel_size)
        iy = int((center.y - min_y) / voxel_size)
        ix = max(0, min(num_x - 1, ix))
        iy = max(0, min(num_y - 1, iy))

        u_center = (ix + 0.5) * tile_u
        v_center = (iy + 0.5) * tile_v

        for loop in face.loops:
            loop[uv_layer].uv = Vector((u_center, v_center))

    bm_final.to_mesh(final_mesh)
    bm_final.free()
    final_mesh.update()

    bpy.data.objects.remove(temp_obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)

    return final_mesh

def get_voxel_instancer_node_group(voxel_size):
    group_name = f"VoxelInstancer_{voxel_size:.6f}"

    if group_name in bpy.data.node_groups:
        return bpy.data.node_groups[group_name]

    group = bpy.data.node_groups.new(group_name, 'GeometryNodeTree')

    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Voxel Size', in_out='INPUT', socket_type='NodeSocketFloat')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

    input_node = group.nodes.new('NodeGroupInput')
    input_node.location = (-800, 0)
    output_node = group.nodes.new('NodeGroupOutput')
    output_node.location = (600, 0)

    scale_node = group.nodes.new('ShaderNodeMath')
    scale_node.operation = 'MULTIPLY'
    scale_node.inputs[1].default_value = 1.02  
    scale_node.location = (-600, 150)

    cube_node = group.nodes.new('GeometryNodeMeshCube')
    cube_node.location = (-400, 150)

    instance_node = group.nodes.new('GeometryNodeInstanceOnPoints')
    instance_node.location = (-200, 0)

    realize_node = group.nodes.new('GeometryNodeRealizeInstances')
    realize_node.location = (0, 0)

    shade_node = group.nodes.new('GeometryNodeSetShadeSmooth')
    shade_node.inputs['Shade Smooth'].default_value = False
    shade_node.location = (200, 0)

    group.links.new(input_node.outputs['Geometry'], instance_node.inputs['Points'])
    group.links.new(input_node.outputs['Voxel Size'], scale_node.inputs[0])
    group.links.new(scale_node.outputs[0], cube_node.inputs['Size'])
    group.links.new(cube_node.outputs['Mesh'], instance_node.inputs['Instance'])
    group.links.new(instance_node.outputs['Instances'], realize_node.inputs['Geometry'])
    group.links.new(realize_node.outputs['Geometry'], shade_node.inputs['Geometry'])
    group.links.new(shade_node.outputs['Geometry'], output_node.inputs['Geometry'])

    for socket in group.interface.items_tree:
        if socket.name == 'Voxel Size' and socket.in_out == 'INPUT':
            socket.default_value = voxel_size
            break

    return group


# ------------------------------------------------------------------------
# Operators
# ------------------------------------------------------------------------

class OBJECT_OT_voxelizer(Operator):
    bl_idname = "object.voxelizer"
    bl_label = "Voxelize Objects"
    bl_options = {"REGISTER", "UNDO"}
    
    def execute(self, context):
        settings = context.scene.voxelizer_settings
        grid_level = settings.grid_level
        
        selected_meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not selected_meshes:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}
        
        for obj in selected_meshes:
            voxelizer_object(obj, context, grid_level)
        
        voxel_size = get_voxel_size(grid_level)
        self.report({'INFO'}, 
            f"Voxelized {len(selected_meshes)} object(s) at grid level {grid_level} "
            f"(voxel size: {voxel_size:.4f} units)")
        
        return {'FINISHED'}

class OBJECT_OT_snap_to_grid(Operator):
    bl_idname = "object.snap_to_voxel_grid"
    bl_label = "Snap to Grid"
    bl_options = {"REGISTER", "UNDO"}
    
    def execute(self, context):
        settings = context.scene.voxelizer_settings
        voxel_size = get_voxel_size(settings.grid_level)
        
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not selected_objects:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}
        
        for obj in selected_objects:
            snapped_location = snap_vector_to_grid(obj.location, voxel_size)
            obj.location = snapped_location
        
        self.report({'INFO'}, 
            f"Snapped {len(selected_objects)} object(s) to grid level {settings.grid_level}")
        
        return {'FINISHED'}

class OBJECT_OT_undo_voxelizer(Operator):
    bl_idname = "object.undo_voxelizer"
    bl_label = "Undo Voxelization"
    bl_options = {"REGISTER", "UNDO"}
    
    def execute(self, context):
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not selected_objects:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}
        
        restored_count = 0
        
        for obj in selected_objects:
            if not obj.get("is_voxelized"):
                continue
            
            source = None
            for child in obj.children:
                if child.get("voxel_source"):
                    source = child
                    break
            
            if not source:
                self.report({'WARNING'}, f"No source found for {obj.name}")
                continue
            
            source_mesh_data = source.data
            source_location = obj.location.copy()
            source_rotation = obj.rotation_euler.copy()
            source_scale = obj.scale.copy()
            
            materials = [mat for mat in obj.data.materials if mat]
            
            old_mesh = obj.data
            
            obj.data = source_mesh_data
            
            obj.data.materials.clear()
            for mat in materials:
                obj.data.materials.append(mat)
            
            obj.location = source_location
            obj.rotation_euler = source_rotation
            obj.scale = source_scale
            
            if "is_voxelized" in obj:
                del obj["is_voxelized"]
            
            source_mesh_to_keep = source.data
            bpy.data.objects.remove(source, do_unlink=True)
            
            if old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
            
            restored_count += 1
        
        if restored_count > 0:
            self.report({'INFO'}, f"Restored {restored_count} object(s) to original state")
        else:
            self.report({'WARNING'}, "No voxelized objects found in selection")
        
        context.view_layer.update()
        return {'FINISHED'}

class OBJECT_OT_voxelizer_texture(Operator):
    bl_idname = "object.voxelizer_texture"
    bl_label = "Voxelize Texture"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.voxelizer_settings
        grid_level = settings.grid_level

        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objects:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}

        processed_count = 0
        skipped_count = 0

        for obj in selected_objects:
            if obj.get("is_voxelized"):
                skipped_count += 1
                continue

            if not obj.data.materials:
                continue

            for mat_slot in obj.material_slots:
                mat = mat_slot.material
                if not mat:
                    continue

                if self.voxelizer_material_output(mat, grid_level, context):
                    processed_count += 1

        if processed_count > 0:
            msg = f"Voxelized {processed_count} material(s) at level {grid_level}"
            if skipped_count > 0:
                msg += f" | Skipped {skipped_count} already voxelized object(s)"
            self.report({'INFO'}, msg)
        else:
            if skipped_count > 0:
                self.report({'WARNING'}, f"Skipped {skipped_count} already voxelized object(s)")
            else:
                self.report({'WARNING'}, "No materials found")

        return {'FINISHED'}

    def voxelizer_material_output(self, material, grid_level, context):
        if not material.use_nodes:
            material.use_nodes = True

        nodes = material.node_tree.nodes
        links = material.node_tree.links
        pixel_divisions = 2 ** (8 - grid_level)

        for node in nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                node.interpolation = 'Closest'

        voxel_group = next((n for n in nodes if n.type == 'GROUP' and n.get("voxel_uv_processor")), None)
        if voxel_group:
            if len(voxel_group.inputs) > 1:
                voxel_group.inputs[1].default_value = pixel_divisions
            return True

        uv_group = self.create_voxel_uv_group(pixel_divisions)
        group_node = nodes.new('ShaderNodeGroup')
        group_node.node_tree = uv_group
        group_node.label = "Voxel UV Processor"
        group_node["voxel_uv_processor"] = True

        tex_coord = next((n for n in nodes if n.type == 'TEX_COORD'), None)
        if not tex_coord:
            tex_coord = nodes.new('ShaderNodeTexCoord')
            tex_coord.location = (group_node.location.x - 400, group_node.location.y)

        try:
            links.new(tex_coord.outputs['UV'], group_node.inputs[0])
        except KeyError:
            return False

        connected = False
        for node in nodes:
            if node.type in {'TEX_IMAGE', 'TEX_CHECKER', 'TEX_BRICK', 'TEX_NOISE'}:
                vec_in = node.inputs.get('Vector')
                if vec_in and not vec_in.links:
                    links.new(group_node.outputs[0], vec_in)
                    connected = True

        if not connected:
            nodes.remove(group_node)
            return False

        return True
    
    def create_voxel_uv_group(self, divisions):
        group_name = "VoxelUVProcessor"
        if group_name in bpy.data.node_groups:
            return bpy.data.node_groups[group_name]

        group = bpy.data.node_groups.new(group_name, 'ShaderNodeTree')

        # Inputs / outputs
        uv_in = group.interface.new_socket(name='UV', in_out='INPUT', socket_type='NodeSocketVector')
        div_in = group.interface.new_socket(name='Divisions', in_out='INPUT', socket_type='NodeSocketFloat')
        aspect_in = group.interface.new_socket(name='Aspect Y/X', in_out='INPUT', socket_type='NodeSocketFloat')
        uv_out = group.interface.new_socket(name='UV', in_out='OUTPUT', socket_type='NodeSocketVector')

        div_in.default_value = divisions
        div_in.min_value = 1
        div_in.max_value = 1024

        aspect_in.default_value = 1.0
        aspect_in.min_value = 0.01
        aspect_in.max_value = 10.0

        group_input = group.nodes.new('NodeGroupInput')
        group_output = group.nodes.new('NodeGroupOutput')
        group_input.location = (-800, 0)
        group_output.location = (600, 0)

        separate = group.nodes.new('ShaderNodeSeparateXYZ')
        separate.location = (-600, 0)

        # Apply aspect scaling to Y before pixelation
        pre_aspect_y = group.nodes.new('ShaderNodeMath')
        pre_aspect_y.operation = 'MULTIPLY'
        pre_aspect_y.location = (-450, -150)
        group.links.new(separate.outputs['Y'], pre_aspect_y.inputs[0])
        group.links.new(group_input.outputs['Aspect Y/X'], pre_aspect_y.inputs[1])

        # Multiply by divisions
        mult_x = group.nodes.new('ShaderNodeMath')
        mult_x.operation = 'MULTIPLY'
        mult_x.location = (-350, 150)

        mult_y = group.nodes.new('ShaderNodeMath')
        mult_y.operation = 'MULTIPLY'
        mult_y.location = (-350, -150)

        group.links.new(separate.outputs['X'], mult_x.inputs[0])
        group.links.new(group_input.outputs['Divisions'], mult_x.inputs[1])
        group.links.new(pre_aspect_y.outputs[0], mult_y.inputs[0])
        group.links.new(group_input.outputs['Divisions'], mult_y.inputs[1])

        # Floor both
        floor_x = group.nodes.new('ShaderNodeMath')
        floor_x.operation = 'FLOOR'
        floor_x.location = (-200, 150)

        floor_y = group.nodes.new('ShaderNodeMath')
        floor_y.operation = 'FLOOR'
        floor_y.location = (-200, -150)

        group.links.new(mult_x.outputs[0], floor_x.inputs[0])
        group.links.new(mult_y.outputs[0], floor_y.inputs[0])

        # Divide back by divisions
        div_x = group.nodes.new('ShaderNodeMath')
        div_x.operation = 'DIVIDE'
        div_x.location = (0, 150)

        div_y = group.nodes.new('ShaderNodeMath')
        div_y.operation = 'DIVIDE'
        div_y.location = (0, -150)

        group.links.new(floor_x.outputs[0], div_x.inputs[0])
        group.links.new(group_input.outputs['Divisions'], div_x.inputs[1])
        group.links.new(floor_y.outputs[0], div_y.inputs[0])
        group.links.new(group_input.outputs['Divisions'], div_y.inputs[1])

        # Undo aspect scaling on Y after pixelation
        post_aspect_y = group.nodes.new('ShaderNodeMath')
        post_aspect_y.operation = 'DIVIDE'
        post_aspect_y.location = (200, -150)
        group.links.new(div_y.outputs[0], post_aspect_y.inputs[0])
        group.links.new(group_input.outputs['Aspect Y/X'], post_aspect_y.inputs[1])

        # Offset half-pixel
        offset_x = group.nodes.new('ShaderNodeMath')
        offset_x.operation = 'ADD'
        offset_x.inputs[1].default_value = 0.5 / divisions
        offset_x.location = (200, 150)
        group.links.new(div_x.outputs[0], offset_x.inputs[0])

        offset_y = group.nodes.new('ShaderNodeMath')
        offset_y.operation = 'ADD'
        offset_y.inputs[1].default_value = 0.5 / divisions
        offset_y.location = (400, -150)
        group.links.new(post_aspect_y.outputs[0], offset_y.inputs[0])

        # Combine and output
        combine = group.nodes.new('ShaderNodeCombineXYZ')
        combine.location = (500, 0)
        group.links.new(offset_x.outputs[0], combine.inputs['X'])
        group.links.new(offset_y.outputs[0], combine.inputs['Y'])
        group.links.new(separate.outputs['Z'], combine.inputs['Z'])
        group.links.new(combine.outputs[0], group_output.inputs[0])

        return group

class OBJECT_OT_undo_voxelizer_texture(Operator):
    bl_idname = "object.undo_voxelizer_texture"
    bl_label = "Undo Texture Voxelization"
    bl_options = {"REGISTER", "UNDO"}
    
    def execute(self, context):
        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not selected_objects:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}
        
        removed_count = 0
        
        for obj in selected_objects:
            if not obj.data.materials:
                continue
            
            for mat_slot in obj.material_slots:
                if not mat_slot.material or not mat_slot.material.use_nodes:
                    continue
                
                mat = mat_slot.material
                nodes = mat.node_tree.nodes
                links = mat.node_tree.links
                
                voxel_nodes = [n for n in nodes if n.type == 'GROUP' and n.get("voxel_uv_processor")]
                
                for voxel_node in voxel_nodes:
                    input_connection = None
                    if len(voxel_node.inputs) > 0 and len(voxel_node.inputs[0].links) > 0:
                        for link in voxel_node.inputs[0].links:
                            input_connection = link.from_socket
                            break
                    
                    output_connections = []
                    if len(voxel_node.outputs) > 0:
                        for link in voxel_node.outputs[0].links[:]:
                            output_connections.append(link.to_socket)
                            links.remove(link)
                    
                    if input_connection:
                        for out_socket in output_connections:
                            links.new(input_connection, out_socket)
                    
                    nodes.remove(voxel_node)
                    removed_count += 1
        
        if removed_count > 0:
            self.report({'INFO'}, f"Removed texture voxelization from {removed_count} material(s)")
        else:
            self.report({'WARNING'}, "No voxelized textures found")
        
        return {'FINISHED'}

# ------------------------------------------------------------------------
# Properties
# ------------------------------------------------------------------------

class VoxelizerSettings(PropertyGroup):
    grid_level: IntProperty(
        name="Grid Level",
        description="Universal voxel grid resolution (1=largest, 8=smallest)",
        default=2,
        min=1,
        max=6,
    )
    
# ------------------------------------------------------------------------
# UI
# ------------------------------------------------------------------------

class VIEW3D_PT_voxelizer(bpy.types.Panel):
    bl_label = "Voxelizer"
    bl_idname = "VIEW3D_PT_voxelizer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Voxelizer"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.voxelizer_settings

        selected_objects = [obj for obj in context.selected_objects if obj.type == 'MESH']
        any_voxelized = any(obj.get("is_voxelized") for obj in selected_objects)

        layout.operator("object.voxelizer", icon='MOD_REMESH', text="Voxelize Objects")

        if any_voxelized:
            layout.operator("object.undo_voxelizer", icon='LOOP_BACK', text="Undo Voxelization")

        layout.operator("object.snap_to_voxel_grid", icon='SNAP_GRID', text="Snap to Grid")

        layout.separator()

        layout.label(text="Voxel Grid Resolution:", icon='GRID')

        for level in range(1, 7):
            row = layout.row(align=True)
            row.scale_y = 1.1

            icon = 'RADIOBUT_ON' if settings.grid_level == level else 'RADIOBUT_OFF'

            op = row.operator("wm.context_set_int", text=f"Level {level}", icon=icon)
            op.data_path = "scene.voxelizer_settings.grid_level"
            op.value = level

            voxel_size = get_voxel_size(level)
            row.label(text=f"{voxel_size:.4f} units")

        layout.separator(factor=0.5)

        current_size = get_voxel_size(settings.grid_level)
        layout.label(text=f"Voxel Size: {current_size:.4f} units")
        layout.label(text=f"Grid Level: {settings.grid_level} of 6")

        if selected_objects:
            status = "voxelized" if any_voxelized else "original"
            layout.label(text=f"Selected Objects: {len(selected_objects)} ({status})",
                         icon='OUTLINER_OB_MESH')
        else:
            layout.label(text="No mesh objects selected", icon='ERROR')

# ------------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------------

classes = (
    VoxelizerSettings,
    OBJECT_OT_voxelizer,
    OBJECT_OT_snap_to_grid,
    OBJECT_OT_undo_voxelizer,
    OBJECT_OT_voxelizer_texture,
    OBJECT_OT_undo_voxelizer_texture,
    VIEW3D_PT_voxelizer, 
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.voxelizer_settings = PointerProperty(type=VoxelizerSettings)

def unregister():
    del bpy.types.Scene.voxelizer_settings
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()