"""Dynamic inputs for balanced floor-area processing."""


def building_source_outputs(wildcards):
    return checkpoints.prepare_building_sources.get(shapes=wildcards.shapes).output


def building_plan_input(wildcards):
    return building_source_outputs(wildcards).manifest


def eubucco_stats_input(wildcards):
    return building_source_outputs(wildcards).eubucco_stats


def read_building_plan(wildcards):
    import json

    path = building_source_outputs(wildcards).manifest
    with open(path) as stream:
        return json.load(stream)


def eubucco_download_inputs(wildcards):
    plan = read_building_plan(wildcards)
    regions = (
        ["eubucco_lat_lon"]
        if plan["eubucco_source"] == "lightweight"
        else sorted(
            {
                nuts2
                for region in plan["regions"].values()
                for nuts2 in region["eubucco_nuts2_ids"]
                if "eubucco"
                in {region["residential_source"], region["commercial_source"]}
            }
        )
    )
    return [
        str(rules.download_eubucco.output.table).format(region=region)
        for region in regions
    ]


def eubucco_download_url(wildcards):
    return internal["resources"]["automatic"][
        f"eubucco_{config['buildings_eubucco']['source']}"
    ].format(
        version=config["buildings_eubucco"]["version"],
        nuts2=wildcards.region,
    )


def microsoft_download_rows(wildcards):
    import csv

    plan = read_building_plan(wildcards)
    quadkeys = {
        key
        for region in plan["regions"].values()
        for key in region["microsoft_quadkeys"]
    }
    with open(rules.download_microsoft_index.output.table, newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["QuadKey"] in quadkeys]
    return sorted(rows, key=lambda row: (row["QuadKey"], row["Url"]))


def microsoft_download_inputs(wildcards):
    counts = {}
    downloads = []
    for row in microsoft_download_rows(wildcards):
        part = counts.get(row["QuadKey"], 0)
        counts[row["QuadKey"]] = part + 1
        downloads.append(
            str(rules.download_microsoft.output.table).format(
                quadkey=row["QuadKey"], part=f"{part:05d}"
            )
        )
    return downloads


def selected_eubucco_input(wildcards):
    outputs = building_source_outputs(wildcards)
    plan = read_building_plan(wildcards)
    if any(
        region["eubucco_nuts2_ids"]
        and "eubucco" in {region["residential_source"], region["commercial_source"]}
        for region in plan["regions"].values()
    ):
        return str(rules.combine_eubucco.output.table).format(shapes=wildcards.shapes)
    return outputs.empty_eubucco


def selected_microsoft_input(wildcards):
    outputs = building_source_outputs(wildcards)
    plan = read_building_plan(wildcards)
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
