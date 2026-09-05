"""Create hectare-level support for national residential space-heating demand."""


rule download_eurostat_building_age:
    output:
        table="<resources>/automatic/eurostat/cens_21dwop_r3.tsv.gz",
    log:
        "<logs>/download_eurostat_building_age.log",
    conda:
        "../envs/download.yaml"
    params:
        url=internal["resources"]["eurostat_building_age"],
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.table} "{params.url}" 2> {log}'


rule prepare_nuts3_building_age:
    input:
        nuts3=rules.prepare_nuts3.output.regions,
        floor_area=rules.prepare_floor_area_totals.output.table,
        census=rules.download_eurostat_building_age.output.table,
    output:
        table="<resources>/automatic/{shapes}/nuts3_building_age.parquet",
    log:
        "<logs>/{shapes}/prepare_nuts3_building_age.log",
    conda:
        "../envs/module.yaml"
    params:
        settings=config["space_heat_weight"]["age"],
    script:
        "../scripts/prepare_nuts3_building_age.py"


checkpoint prepare_space_heat_weight_batches:
    input:
        plan=building_plan_input,
        stats=eubucco_stats_input,
    output:
        manifest="<resources>/automatic/{shapes}/space_heat_weight/batches.json",
    log:
        "<logs>/{shapes}/prepare_space_heat_weight_batches.log",
    conda:
        "../envs/module.yaml"
    params:
        batch_count=config["space_heat_weight"]["nuts3_batches"],
    script:
        "../scripts/prepare_floor_area_batches.py"


rule prepare_space_heat_sv_statistics:
    input:
        nuts3=rules.prepare_nuts3.output.regions,
        floor_area=rules.prepare_floor_area_totals.output.table,
        plan=building_plan_input,
        eubucco=selected_eubucco_input,
    output:
        table="<resources>/automatic/{shapes}/space_heat_weight/sv_statistics.parquet",
    log:
        "<logs>/{shapes}/prepare_space_heat_sv_statistics.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    params:
        settings=config["space_heat_weight"],
        residential_type=config["floor_area"]["eubucco"]["residential_type"],
    script:
        "../scripts/prepare_space_heat_sv_statistics.py"


rule create_space_heat_weight_batch:
    input:
        scope=rules.prepare_shapes.output.scope,
        nuts3=rules.prepare_nuts3.output.regions,
        floor_area=rules.prepare_floor_area_totals.output.table,
        plan=building_plan_input,
        batches=space_heat_weight_batch_plan_input,
        eubucco=selected_eubucco_input,
        microsoft=selected_microsoft_input,
        age=rules.prepare_nuts3_building_age.output.table,
        sv_statistics=rules.prepare_space_heat_sv_statistics.output.table,
    output:
        partials=directory(
            "<resources>/automatic/{shapes}/space_heat_weight/batches/{batch}"
        ),
    log:
        "<logs>/{shapes}/create_space_heat_weight_batch_{batch}.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    params:
        space_heat_weight=config["space_heat_weight"],
        residential_type=config["floor_area"]["eubucco"]["residential_type"],
        raster=config["raster"],
    script:
        "../scripts/create_nuts3_space_heat_weight.py"


rule merge_space_heat_weight:
    input:
        shapes=rules.prepare_shapes.output.shapes,
        plan=building_plan_input,
        batches=space_heat_weight_batch_inputs,
    output:
        raster="<residential_space_heat_weight>",
        plot="<results>/{shapes}/visualiation/residential_space_heat_weight.png",
        diagnostics="<resources>/automatic/{shapes}/space_heat_weight/diagnostics.parquet",
    log:
        "<logs>/{shapes}/merge_space_heat_weight.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    params:
        space_heat_weight=config["space_heat_weight"],
        raster=config["raster"],
    script:
        "../scripts/merge_space_heat_weight.py"
