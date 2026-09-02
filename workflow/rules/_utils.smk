"""Dynamic inputs for adaptive EUBUCCO processing."""


def read_eubucco_plan(wildcards):
    import json

    path = checkpoints.prepare_eubucco_download.get(
        shapes=wildcards.shapes
    ).output.manifest
    with open(path) as stream:
        return json.load(stream)


def eubucco_plan_input(wildcards):
    return checkpoints.prepare_eubucco_download.get(
        shapes=wildcards.shapes
    ).output.manifest


def eubucco_stats_input(wildcards):
    return checkpoints.prepare_eubucco_download.get(
        shapes=wildcards.shapes
    ).output.eubucco_stats


def eubucco_region_ids(wildcards):
    return read_eubucco_plan(wildcards)["regions"][wildcards.nuts3]["region_ids"]


def floor_area_partial_inputs(wildcards):
    plan = read_eubucco_plan(wildcards)
    return [
        str(rules.create_nuts3_floor_area.output.raster).format(
            shapes=wildcards.shapes, nuts3=nuts3
        )
        for nuts3 in plan["regions"]
    ]
