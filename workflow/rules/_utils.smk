"""Dynamic inputs for balanced floor-area processing."""


def building_source_outputs(wildcards):
    return checkpoints.prepare_building_sources.get(shapes=wildcards.shapes).output


def building_plan_input(wildcards):
    return building_source_outputs(wildcards).manifest


def eubucco_stats_input(wildcards):
    return building_source_outputs(wildcards).eubucco_stats


def microsoft_index_input(wildcards):
    return building_source_outputs(wildcards).microsoft_index


def selected_eubucco_input(wildcards):
    import json

    outputs = building_source_outputs(wildcards)
    with open(outputs.manifest) as stream:
        plan = json.load(stream)
    if any(
        region["eubucco_nuts2_ids"]
        and "eubucco" in {region["residential_source"], region["commercial_source"]}
        for region in plan["regions"].values()
    ):
        return str(rules.combine_eubucco.output.table).format(shapes=wildcards.shapes)
    return outputs.empty_eubucco


def selected_microsoft_input(wildcards):
    import json

    outputs = building_source_outputs(wildcards)
    with open(outputs.manifest) as stream:
        plan = json.load(stream)
    if any(region["microsoft_quadkeys"] for region in plan["regions"].values()):
        return str(rules.combine_microsoft.output.table).format(shapes=wildcards.shapes)
    return outputs.empty_microsoft


def read_floor_area_batch_plan(wildcards):
    import json

    path = checkpoints.prepare_floor_area_batches.get(
        shapes=wildcards.shapes
    ).output.manifest
    with open(path) as stream:
        return json.load(stream)


def floor_area_batch_plan_input(wildcards):
    return checkpoints.prepare_floor_area_batches.get(
        shapes=wildcards.shapes
    ).output.manifest


def floor_area_batch_inputs(wildcards):
    plan = read_floor_area_batch_plan(wildcards)
    return [
        str(rules.create_floor_area_batch.output.partials).format(
            shapes=wildcards.shapes, batch=batch
        )
        for batch in plan["batches"]
    ]


def read_space_heat_weight_batch_plan(wildcards):
    import json

    path = checkpoints.prepare_space_heat_weight_batches.get(
        shapes=wildcards.shapes
    ).output.manifest
    with open(path) as stream:
        return json.load(stream)


def space_heat_weight_batch_plan_input(wildcards):
    return checkpoints.prepare_space_heat_weight_batches.get(
        shapes=wildcards.shapes
    ).output.manifest


def space_heat_weight_batch_inputs(wildcards):
    plan = read_space_heat_weight_batch_plan(wildcards)
    return [
        str(rules.create_space_heat_weight_batch.output.partials).format(
            shapes=wildcards.shapes, batch=batch
        )
        for batch in plan["batches"]
    ]
