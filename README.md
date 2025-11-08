# Voxelizer

![voxelizer-thumb](https://github.com/user-attachments/assets/99961701-ac22-410d-9c85-ebcff554a802)

**Author:** The French Monkey (TFMSTYLE)  
**Version:** 1.0.0  

---

## Overview

**Voxelizer** converts mesh objects into **voxel representations** using a universal grid system.  
Each voxel corresponds to a cube cell of fixed resolution, enabling stylized blocky reconstructions of any mesh.  

The system also provides **texture voxelization**, **grid snapping**, and **undo functionality** for both geometry and material operations.

---

## Parameters

### Grid Level
- **Name:** Grid Level  
- **Type:** Integer  
- **Description:**  
  Defines the voxel grid resolution.  
  A higher grid level creates smaller voxels (more detail), while a lower level generates larger voxels (less detail).  
  *(Default: 2, Range: 1–6)*

---

## Core Features

### Universal Grid System
- **Consistent voxel size** across all objects, derived from `Grid Level`.  
- Snaps geometry and positions to a **uniform 3D grid** for structural consistency.  
- Uses a BVH-based spatial lookup to determine voxel occupancy.  

### Source Preservation
- The original mesh is stored in a hidden **voxel source object** for each voxelized model.  
- Enables safe restoration when undoing the voxelization.

### Texture Pixelation
- Creates **voxelized UV processing groups** in materials to match texture pixels to voxel grid divisions.  
- Ideal for low-poly or pixel-art-style rendering.

---

## Operators

### Voxelize Objects
**Operator:** `object.voxelizer`  
Converts selected mesh objects into voxel meshes based on the active **Grid Level**.

**Behavior:**
1. Evaluates the mesh in world space.  
2. Builds a **BVH tree** to test voxel intersections.  
3. Generates a grid of cube instances at occupied voxel positions.  
4. Preserves original materials.  
5. Snaps final object to the grid for perfect alignment.  

**Reports:**  
Displays the number of voxelized objects and the effective voxel size in world units.

---

### Snap to Grid
**Operator:** `object.snap_to_voxel_grid`  
Snaps the selected objects’ world positions to the voxel grid based on the current **Grid Level**.  

Useful for aligning models to voxel coordinates or maintaining consistent offsets between voxelized objects.

---

### Undo Voxelization
**Operator:** `object.undo_voxelizer`  
Restores voxelized objects to their original geometry using the hidden source mesh stored during voxelization.  

**Behavior:**
- Finds the original mesh object marked as `voxel_source`.  
- Reassigns it as the active mesh data.  
- Restores materials, transforms, and removes voxel metadata.  

If no voxelized data is found, the operator safely skips affected objects.

---

### Voxelize Texture
**Operator:** `object.voxelizer_texture`  
Applies voxelization to **material textures**, pixelating UVs to match voxel resolution.

**Process:**
- Adjusts UV coordinates to discrete steps based on `Grid Level`.  
- Inserts a **“Voxel UV Processor”** node group before texture nodes.  
- Ensures texture interpolation is set to **Closest** for blocky precision.  

**Outputs:**  
Pixelated textures that visually match the geometric voxel grid.

---

### Undo Texture Voxelization
**Operator:** `object.undo_voxelizer_texture`  
Removes the “Voxel UV Processor” nodes and restores original texture mapping.  

Automatically reconnects all previous node links, preserving material consistency.

---

## Node Systems

### Geometry Node Group — `VoxelInstancer`
Handles voxel cube instancing for each grid point.

**Inputs:**
- `Geometry`: Base point data (from grid occupancy).
- `Voxel Size`: Cube scale for voxel grid.

**Outputs:**
- `Geometry`: Combined voxel mesh output.

**Features:**
- Smooth shading toggle (off by default).  
- Slight scale multiplier (1.02×) for voxel overlap prevention.  
- Optimized instancing via `Instance on Points` and `Realize Instances`.

---

### Shader Node Group — `VoxelUVProcessor`
Pixelates UV coordinates based on grid-level divisions.  

**Inputs:**
- `UV`: Original UV coordinates.  
- `Divisions`: Number of pixel cells along UV axes (based on grid level).  
- `Aspect Y/X`: Aspect correction factor for non-square textures.  

**Outputs:**
- `UV`: Adjusted, voxelized UV coordinates.

**Functionality:**
1. Separates and scales UV components.  
2. Applies floor rounding to snap to pixel cells.  
3. Reconstructs a combined UV output with half-pixel offset correction.

---

## Internal Data

### Object Metadata
- **`is_voxelized`** → Marks voxelized objects.  
- **`voxel_source`** → Stored on hidden child objects containing original geometry.

### Mesh Replacement
- Old meshes are automatically removed from memory if unused after voxelization.

---

## Example Workflow

1. Select your target mesh objects.  
2. Set **Grid Level** (1 = coarse, 6 = fine).  
3. Run **“Voxelize Objects”** to generate blocky geometry.  
4. (Optional) Apply **“Voxelize Texture”** for pixel-aligned surface textures.  
5. Snap all objects to the grid using **“Snap to Grid”** for structural uniformity.  
6. To revert, use **“Undo Voxelization”** or **“Undo Texture Voxelization”**.

---

## Notes

- Works entirely in **object space**, supports any mesh topology.  
- Geometry node-based instancing ensures efficient voxel generation.  
- Texture processing integrates seamlessly into existing node networks.  
- Safe undo/redo support through Blender’s operator stack.  

**Voxelizer** transforms meshes and materials into precise voxel structures — perfect for stylized 3D art, motion graphics, and game asset preprocessing.
