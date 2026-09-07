"""Allocate physical floor area and retain residential heat support."""


checkpoint prepare_floor_area_batches:
    input:
        plan=building_plan_input,
        stats=eubucco_stats_input,
    output:
        manifest="<resources>/automatic/{shapes}/heat_rasters/batches.json",
    log:
        "<logs>/{shapes}/prepare_floor_area_batches.log",
    conda:
        "../envs/module.yaml"
    params:
        batch_count=config["processing"]["nuts3_batches"],
    script:
        "../scripts/prepare_floor_area_batches.py"


rule prepare_floor_area_totals:
    input:
        nuts3=rules.prepare_nuts3.output.regions,
        nuts3_source=rules.download_nuts3.output.geojson,
        census=rules.download_eurostat_floor_area.output.table,
        population=rules.extract_ghsl_population.output.raster,
        eubucco_stats=eubucco_stats_input,
        plan=building_plan_input,
        microsoft_totals=selected_microsoft_totals_input,
    output:
        table="<resources>/automatic/{shapes}/floor_area_totals.parquet",
    log:
        "<logs>/{shapes}/prepare_floor_area_totals.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    params:
        eurostat=config["eurostat"],
        population=config["population_ghsl"],
        eubucco=config["buildings_eubucco"],
        proxies=config["data_proxies"],
        country_codes=internal["country_codes"],
    script:
        "../scripts/prepare_floor_area_totals.py"


rule create_floor_area_batch:
    input:
        scope=rules.prepare_shapes.output.scope,
        nuts3=rules.prepare_nuts3.output.regions,
        totals=rules.prepare_floor_area_totals.output.table,
        plan=building_plan_input,
        batches=floor_area_batch_plan_input,
        eubucco=selected_eubucco_input,
        microsoft=selected_microsoft_input,
        microsoft_statistics=selected_microsoft_statistics_input,
        population=rules.extract_ghsl_population.output.raster,
    output:
        partials=directory(
            "<resources>/automatic/{shapes}/heat_rasters/batches/{batch}"
        ),
    log:
        "<logs>/{shapes}/create_floor_area_batch_{batch}.log",
    conda:
        "../envs/module.yaml"
    threads: 1
    resources:
        mem_mb=4096,
    params:
        eubucco=config["buildings_eubucco"],
        microsoft=config["buildings_microsoft"],
        population=config["population_ghsl"],
        surface_volume=config["space_heat_weight"]["surface_volume"],
        population_resampling=config["space_heat_weight"]["population"]["resampling"],
        raster=intermediate_raster_settings(),
    script:
        "../scripts/create_nuts3_floor_area.py"
