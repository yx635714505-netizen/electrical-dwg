# Electrical Placement Verification Implementation Plan

> Historical implementation plan. The tasks below describe work in the original staging workspace. For the current procedure, see [the placement pipeline](../../../references/placement-pipeline.md).

**Goal:** Turn real-wall-minus-opening recognition, independent geometry verification, and complete delivery checks into reusable executable checks.

**Architecture:** A standard-library Python geometry module subtracts opening intervals from actual support faces. A native-readback adapter resolves nested symbol geometry and records unsupported geometry as pending. A delivery gate binds required checks, complete point/page inventories and visual evidence to file hashes. Existing project coordinates and expected counts do not serve as proof.

**Tech Stack:** Python 3 standard library; AutoCAD 2020 read-only native Database export through the existing shared CAD pool where needed.

**Spec:** User's approved three priorities plus electrical-dwg/references/placement-verification.md (V35).

## Global Constraints
- No computer-use, desktop CAD, T3 conversion, original DWG changes, shared CAD configuration changes, or old-project regeneration.
- Preserve V35 room-side, column occlusion, furniture/fixtures, control and point-by-point visual requirements. Unsupported automation remains pending; do not claim these requirements are solved by segment support alone.
- Source inventory, saved DWG inventory, and verification rows are distinct. Counts derive from actual inputs, not fixed sample project counts.
- Independent readback and final-file hash binding; missing reports or visual evidence block release.

## Review Focus
- Nested rotation/mirror/nonuniform scaling; infer mounting edge only from supported actual geometry.
- Door aperture subtraction even when the wall bounding box spans the opening.
- Slanted faces and partial overlap, including a symbol center outside a door but its full edge overlaps.
- Extra/missing/duplicate native instances or source expectations, including empty evidence and stale hashes.
- Changed final DWG, report files, visual artifacts, or required-category manifest cannot reuse old success.

## Task 1: Support geometry and regression tests
Files: scripts/placement_geometry.py; tests/test_placement_geometry.py.
- [x] Write tests for interval subtraction, overlap, slanted support, finite geometry, touching endpoints, nested transforms.
- [x] Run tests and observe missing-module failures.
- [x] Implement affine transforms, segment/polygon geometry, usable support spans and complete-edge validation.
- [x] Run tests; verify project-independent units and tolerances.

## Task 2: Independent saved-geometry checks
Files: scripts/verify_placement.py; work/electrical-placement-v36/项目回归脚本 (project-only); tests/test_verify_placement.py.
Interfaces: validate_geometry(source_geometry, actual_inventory, tolerance) -> report. Source entries contain faces/openings/obstacles and provenance. Actual entries contain final handles, floor, mountingEdge and required body footprint for complete acceptance. No expected target coordinate is accepted as wall-support evidence.
- [x] Write failing tests for missing/extra instances, unsupported extraction, crossing openings, ambiguous mounting edge and collisions.
- [x] Implement inventory-driven evaluation, nested ARC chord extraction for socket symbols, declared symbol profiles, runtime floor transformations and evidence.
- [x] Replay V03 and V04 with independent saved DWG geometry; confirm known three invalid socket placements fail in V03 and pass their corrected positions in V04.
- [x] Keep unsupported instances and unreviewed room/control/visual checks pending.

## Task 3: Complete delivery gate
Files: scripts/validate_delivery.py; tests/test_validate_delivery.py.
Interfaces: validate_delivery(manifest_path) -> report with passed/failed/pending, executionStatus, reviewDraftReady and constructionReady.
- [x] Write failing tests for missing reports, stale DWG/report/source/visual hashes, absent pages, extra native instances, falsely marked empty checks, and engineering-pending status.
- [x] Implement required check inventory, separate pointwise coverage, report status aggregation and artifact hash checks; gate exits nonzero unless the requested release mode is met.
- [x] Verify known incomplete sample project evidence is blocked rather than falsely reclassified as fully checked.

## Task 4: Install, document and verify
- [x] Install verified scripts/tests under electrical-dwg with backups of changed references.
- [x] Add schema, CLI usage, dependency/invalidation flow, supported/unsupported geometry, and scope to placement-verification.md / entrypoints.
- [x] Run full tests and skill validation, inspect installed-file hashes and write findings with timing to output/电气定位链路_V36_验证.
- [x] Preserve old project DWGs and source files; report exact limitations and tested results.

Completion evidence: output/电气定位链路_V36_验证/实施与验证说明.txt. The archived regression is scoped, not whole-project acceptance; unsupported native geometry remains pending.
