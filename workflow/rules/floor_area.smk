"""Create hectare-level residential and commercial floor area."""


checkpoint prepare_eubucco_download:
    input:
        nuts3=rules.prepare_nuts3.output.regions,
    output:
        manifest="<resources>/automatic/{shapes}/eubucco/plan.json",
        eubucco_nuts="<resources>/automatic/{shapes}/eubucco/NUTS-regions-2016.parquet",
        eubucco_stats="<resources>/automatic/{shapes}/eubucco/region-stats.parquet",
    log:
        "<logs>/{shapes}/prepare_eubucco_download.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        settings=config["floor_area"]["eubucco"],
        sources=internal["resources"]["automatic"],
    script:
        "../scripts/prepare_eubucco_download.py"


rule download_eubucco:
    input:
        plan=eubucco_plan_input,
    output:
        downloads=protected(
            directory(
                f"<resources>/automatic/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/downloads"
            )
        ),
    log:
        f"<logs>/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/download.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        sources=internal["resources"]["automatic"],
    script:
        "../scripts/download_eubucco.py"


rule process_eubucco:
    input:
        plan=eubucco_plan_input,
        downloads=rules.download_eubucco.output.downloads,
    output:
        partitions=directory(
            f"<resources>/automatic/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/processed"
        ),
    log:
        f"<logs>/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/process.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    script:
        "../scripts/process_eubucco.py"


rule combine_eubucco:
    input:
        partitions=rules.process_eubucco.output.partitions,
    output:
        table=f"<resources>/automatic/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/buildings.parquet",
    log:
        f"<logs>/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/combine.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    script:
        "../scripts/combine_eubucco.py"


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


rule prepare_floor_area_totals:
    input:
        nuts3=rules.prepare_nuts3.output.regions,
        nuts3_source=rules.download_nuts3.output.geojson,
        census=rules.download_eurostat_floor_area.output.table,
        population=rules.extract_ghsl_population.output.raster,
        eubucco_stats=eubucco_stats_input,
    output:
        table="<resources>/automatic/{shapes}/floor_area_totals.parquet",
    log:
        "<logs>/{shapes}/prepare_floor_area_totals.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    params:
        floor_area=config["floor_area"],
        proxies=config["data_proxies"],
        country_codes=internal["country_codes"],
    script:
        "../scripts/prepare_floor_area_totals.py"


rule create_nuts3_floor_area:
    input:
        shapes=rules.prepare_shapes.output.shapes,
        nuts3=rules.prepare_nuts3.output.regions,
        population=rules.extract_ghsl_population.output.raster,
        totals=rules.prepare_floor_area_totals.output.table,
        plan=eubucco_plan_input,
        eubucco=rules.combine_eubucco.output.table,
    output:
        raster="<resources>/automatic/{shapes}/floor_area/nuts3/{nuts3}.tif",
    log:
        "<logs>/{shapes}/create_floor_area_{nuts3}.log",
    conda:
        "../envs/module.yaml"
    threads: 1
    resources:
        mem_mb=4096,
    params:
        floor_area=config["floor_area"],
        raster=config["raster"],
        region_ids=eubucco_region_ids,
    script:
        "../scripts/create_nuts3_floor_area.py"


rule merge_floor_area:
    input:
        shapes=rules.prepare_shapes.output.shapes,
        plan=eubucco_plan_input,
        partials=floor_area_partial_inputs,
    output:
        raster="<resources>/automatic/{shapes}/floor_area.tif",
        residential_plot="<resources>/automatic/{shapes}/floor_area_residential.png",
        commercial_plot="<resources>/automatic/{shapes}/floor_area_commercial.png",
    log:
        "<logs>/{shapes}/merge_floor_area.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    params:
        floor_area=config["floor_area"],
        raster=config["raster"],
    script:
        "../scripts/merge_floor_area.py"
