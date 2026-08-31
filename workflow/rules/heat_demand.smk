"""Regionalise annual useful heat demand through NUTS 3 to hectares."""


rule create_heat_demand_density:
    input:
        shapes="<shapes>",
        nuts3=rules.prepare_nuts3.output.regions,
        annual_demand="<annual_heat_demand>",
        residential_proxy=rules.download_residential_heat_density.output.raster,
        non_residential_proxy=rules.download_non_residential_heat_density.output.raster,
    output:
        raster="<heat_demand_density>",
        nuts3="<nuts3_heat_demand>",
    log:
        "<logs>/{shapes}/create_heat_demand_density_{year}.log",
    conda:
        "../envs/module.yaml"
    params:
        heat_demand=config["heat_demand"],
        raster=config["raster"],
        source_grid=internal["source_grid"],
    script:
        "../scripts/create_heat_demand.py"
