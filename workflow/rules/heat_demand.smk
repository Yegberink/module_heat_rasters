"""Regionalise annual useful heat demand through NUTS 3 to hectares."""


rule create_heat_demand_density:
    input:
        shapes=rules.prepare_shapes.output.shapes,
        nuts3=rules.prepare_nuts3.output.regions,
        annual_demand="<annual_heat_demand>",
        floor_area=rules.merge_floor_area.output.raster,
    output:
        raster="<heat_demand_density>",
        regions="<regional_heat_demand>",
    log:
        "<logs>/{shapes}/create_heat_demand_density_{year}.log",
    conda:
        "../envs/module.yaml"
    params:
        heat_demand=config["heat_demand"],
        raster=config["raster"],
        floor_area_reference_year=config["floor_area"]["reference_year"],
    script:
        "../scripts/create_heat_demand.py"
