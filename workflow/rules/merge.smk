"""Write both public rasters from shared physical floor-area support."""


rule merge_heat_rasters:
    input:
        shapes=rules.prepare_shapes.output.shapes,
        plan=building_plan_input,
        batches=floor_area_batch_plan_input,
        support=floor_area_batch_inputs,
        weights=space_heat_weight_batch_inputs,
    output:
        floor_area="<floor_area>",
        residential_space_heat_weight="<residential_space_heat_weight>",
        residential_plot="<results>/{shapes}/visualiation/floor_area_residential.png",
        commercial_plot="<results>/{shapes}/visualiation/floor_area_commercial.png",
        heat_plot="<results>/{shapes}/visualiation/residential_space_heat_weight.png",
        diagnostics="<resources>/automatic/{shapes}/space_heat_weight/diagnostics.parquet",
    log:
        "<logs>/{shapes}/merge_heat_rasters.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    params:
        eurostat=config["eurostat"],
        population=config["population_ghsl"],
        eubucco=config["buildings_eubucco"],
        microsoft=config["buildings_microsoft"],
        space_heat_weight=config["space_heat_weight"],
        intermediate=intermediate_raster_settings(),
        raster=config["raster"],
    script:
        "../scripts/merge_heat_rasters.py"
