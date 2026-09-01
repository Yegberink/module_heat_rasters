"""Create hectare-level residential and commercial floor area."""


rule extract_ghsl_population:
    input:
        rules.download_ghsl_population.output.archive,
    output:
        raster=f"<resources>/automatic/ghsl/pop_{config['floor_area']['ghsl_epoch']}_100.tif",
    log:
        "<logs>/extract_ghsl_population.log",
    params:
        internal_paths=internal["resources"]["automatic"]["ghsl_stem"].format(
            epoch=config["floor_area"]["ghsl_epoch"],
            resolution=config["floor_area"]["ghsl_resolution"],
        )
        + "_V1_0.tif",
    wrapper:
        "v9.12.0/utils/libarchive/extract"


rule create_floor_area:
    input:
        shapes="<shapes>",
        nuts3=rules.prepare_nuts3.output.regions,
        nuts3_source=rules.download_nuts3.output.geojson,
        census=rules.download_eurostat_floor_area.output.table,
        population=rules.extract_ghsl_population.output.raster,
        eubucco_nuts=rules.download_eubucco_nuts.output.table,
        eubucco_stats=rules.download_eubucco_stats.output.table,
    output:
        raster="<resources>/automatic/{shapes}/floor_area.tif",
        residential_plot="<resources>/automatic/{shapes}/floor_area_residential.png",
        commercial_plot="<resources>/automatic/{shapes}/floor_area_commercial.png",
    log:
        "<logs>/{shapes}/create_floor_area.log",
    conda:
        "../envs/module.yaml"
    params:
        floor_area=config["floor_area"],
        proxies=config["data_proxies"],
        raster=config["raster"],
        eubucco=internal["resources"]["automatic"],
        country_codes=internal["country_codes"],
    message:
        "Create Census- and EUBUCCO-based hectare floor area."
    script:
        "../scripts/create_floor_area.py"
