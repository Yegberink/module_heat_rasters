"""Create hectare-level residential and commercial floor area."""


checkpoint prepare_building_sources:
    input:
        regions=rules.prepare_nuts3.output.regions,
        microsoft_index=f"<resources>/automatic/microsoft/{config['data_proxies']['microsoft']['release']}/dataset-links.csv",
    output:
        manifest="<resources>/automatic/{shapes}/buildings/plan.json",
        eubucco_nuts="<resources>/automatic/{shapes}/eubucco/NUTS-regions-2016.parquet",
        eubucco_stats="<resources>/automatic/{shapes}/eubucco/region-stats.parquet",
        empty_eubucco="<resources>/automatic/{shapes}/buildings/empty_eubucco.parquet",
        empty_microsoft="<resources>/automatic/{shapes}/buildings/empty_microsoft.parquet",
    log:
        "<logs>/{shapes}/prepare_building_sources.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        sources=internal["resources"]["automatic"],
        eubucco=config["floor_area"]["eubucco"],
        eubucco_countries=internal["resources"]["eubucco_countries"],
        microsoft=config["data_proxies"]["microsoft"],
    script:
        "../scripts/prepare_building_sources.py"


checkpoint prepare_floor_area_batches:
    input:
        plan=building_plan_input,
        stats=eubucco_stats_input,
    output:
        manifest="<resources>/automatic/{shapes}/floor_area/batches.json",
    log:
        "<logs>/{shapes}/prepare_floor_area_batches.log",
    conda:
        "../envs/module.yaml"
    params:
        batch_count=config["floor_area"]["nuts3_batches"],
    script:
        "../scripts/prepare_floor_area_batches.py"


rule download_eubucco:
    output:
        table=update(
            f"<resources>/automatic/eubucco/v{config['floor_area']['eubucco']['version']}/{config['floor_area']['eubucco']['source']}/downloads/{{region}}.parquet"
        ),
    log:
        f"<logs>/eubucco/v{config['floor_area']['eubucco']['version']}/{config['floor_area']['eubucco']['source']}/download_{{region}}.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        url=eubucco_download_url,
    script:
        "../scripts/download_eubucco.py"


rule process_eubucco:
    input:
        plan=building_plan_input,
        regions=rules.prepare_nuts3.output.regions,
        downloads=eubucco_download_inputs,
    output:
        partitions=directory(
            f"<resources>/automatic/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/{config['floor_area']['eubucco']['source']}/processed"
        ),
    log:
        f"<logs>/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/{config['floor_area']['eubucco']['source']}/process.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    script:
        "../scripts/process_eubucco.py"


rule combine_eubucco:
    input:
        plan=building_plan_input,
        partitions=rules.process_eubucco.output.partitions,
    output:
        table=f"<resources>/automatic/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/{config['floor_area']['eubucco']['source']}/buildings.parquet",
    log:
        f"<logs>/{{shapes}}/eubucco/v{config['floor_area']['eubucco']['version']}/{config['floor_area']['eubucco']['source']}/combine.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    script:
        "../scripts/combine_eubucco.py"


rule download_microsoft_index:
    output:
        table=update(
            f"<resources>/automatic/microsoft/{config['data_proxies']['microsoft']['release']}/dataset-links.csv"
        ),
    log:
        f"<logs>/microsoft/{config['data_proxies']['microsoft']['release']}/download_index.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        url=internal["resources"]["automatic"]["microsoft_index"].format(
            release=config["data_proxies"]["microsoft"]["release"]
        ),
    shell:
        'test -e {output.table} || curl -fL --retry 3 --create-dirs -o {output.table} "{params.url}" 2> {log}'


rule download_microsoft:
    input:
        index=rules.download_microsoft_index.output.table,
    output:
        table=update(
            f"<resources>/automatic/microsoft/{config['data_proxies']['microsoft']['release']}/downloads/{{quadkey}}-{{part}}.csv.gz"
        ),
    log:
        f"<logs>/microsoft/{config['data_proxies']['microsoft']['release']}/download_{{quadkey}}_{{part}}.log",
    wildcard_constraints:
        quadkey="[0-3]{9}",
        part="[0-9]{5}",
    conda:
        "../envs/eubucco-download.yaml"
    script:
        "../scripts/download_microsoft.py"


rule process_microsoft:
    input:
        plan=building_plan_input,
        regions=rules.prepare_nuts3.output.regions,
        downloads=microsoft_download_inputs,
    output:
        partitions=directory("<resources>/automatic/{shapes}/microsoft/processed"),
    log:
        "<logs>/{shapes}/microsoft/process.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    script:
        "../scripts/process_microsoft.py"


rule combine_microsoft:
    input:
        partitions=rules.process_microsoft.output.partitions,
    output:
        table="<resources>/automatic/{shapes}/microsoft/buildings.parquet",
    log:
        "<logs>/{shapes}/microsoft/combine.log",
    conda:
        "../envs/module.yaml"
    script:
        "../scripts/combine_microsoft.py"


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
        plan=building_plan_input,
        microsoft=selected_microsoft_input,
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


rule create_floor_area_batch:
    input:
        scope=rules.prepare_shapes.output.scope,
        nuts3=rules.prepare_nuts3.output.regions,
        totals=rules.prepare_floor_area_totals.output.table,
        plan=building_plan_input,
        batches=floor_area_batch_plan_input,
        eubucco=selected_eubucco_input,
        microsoft=selected_microsoft_input,
    output:
        partials=directory("<resources>/automatic/{shapes}/floor_area/batches/{batch}"),
    log:
        "<logs>/{shapes}/create_floor_area_batch_{batch}.log",
    conda:
        "../envs/module.yaml"
    threads: 1
    resources:
        mem_mb=4096,
    params:
        floor_area=config["floor_area"],
        raster=config["raster"],
    script:
        "../scripts/create_nuts3_floor_area.py"


rule merge_floor_area:
    input:
        shapes=rules.prepare_shapes.output.shapes,
        plan=building_plan_input,
        batches=floor_area_batch_inputs,
    output:
        raster="<floor_area>",
        residential_plot="<results>/{shapes}/visualiation/floor_area_residential.png",
        commercial_plot="<results>/{shapes}/visualiation/floor_area_commercial.png",
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
