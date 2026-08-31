"""Regionalise heated gross floor area."""


rule create_nuts3_floor_area:
    input:
        shapes="<shapes>",
        nuts3=rules.prepare_nuts3.output.regions,
        census=rules.download_eurostat_floor_area.output.table,
        residential_proxy=rules.download_residential_floor_area.output.raster,
        non_residential_proxy=rules.download_non_residential_floor_area.output.raster,
    output:
        table="<nuts3_floor_area>",
    log:
        "<logs>/{shapes}/create_nuts3_floor_area.log",
    conda:
        "../envs/module.yaml"
    params:
        floor_area=config["floor_area"],
        source_grid=internal["source_grid"],
    script:
        "../scripts/create_nuts3_floor_area.py"


rule create_floor_area:
    input:
        shapes="<shapes>",
        nuts3=rules.prepare_nuts3.output.regions,
        totals=rules.create_nuts3_floor_area.output.table,
        residential=rules.download_residential_floor_area.output.raster,
        non_residential=rules.download_non_residential_floor_area.output.raster,
    output:
        raster="<floor_area>",
    log:
        "<logs>/{shapes}/create_floor_area.log",
    conda:
        "../envs/module.yaml"
    params:
        raster=config["raster"],
        source_grid=internal["source_grid"],
    message:
        "Regionalise NUTS-3 heated gross floor area to hectares."
    script:
        "../scripts/create_floor_area.py"
