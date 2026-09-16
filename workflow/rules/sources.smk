"""Acquire validated sources and prepare geography and building support."""


rule download_nuts3:
    output:
        geojson="<resources>/automatic/gisco/nuts3.geojson",
    log:
        "<logs>/download_nuts3.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        kind="nuts3",
        url=internal["resources"]["automatic"]["nuts3"],
    script:
        "../scripts/download.py"


rule download_eurostat_floor_area:
    output:
        table="<resources>/automatic/eurostat/cens_21dwbnr_r3.tsv.gz",
    log:
        "<logs>/download_eurostat_floor_area.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        kind="floor_area",
        year=config["eurostat"]["reference_year"],
        url=internal["resources"]["automatic"]["eurostat_floor_area"],
    script:
        "../scripts/download.py"


rule download_ghsl_population:
    output:
        archive=f"<resources>/automatic/ghsl/pop_{config['population_ghsl']['epoch']}_100.zip",
    log:
        "<logs>/download_ghsl_population.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        kind="population",
        resolution=config["population_ghsl"]["resolution"],
        member=internal["resources"]["automatic"]["ghsl_stem"].format(
            epoch=config["population_ghsl"]["epoch"],
            resolution=config["population_ghsl"]["resolution"],
        )
        + "_V1_0.tif",
        url=internal["resources"]["automatic"]["ghsl_population"].format(
            stem=internal["resources"]["automatic"]["ghsl_stem"].format(
                epoch=config["population_ghsl"]["epoch"],
                resolution=config["population_ghsl"]["resolution"],
            )
        ),
    script:
        "../scripts/download.py"


rule prepare_shapes:
    input:
        shapes="<shapes>",
    output:
        shapes="<resources>/automatic/{shapes}/land_shapes.parquet",
        scope="<resources>/automatic/{shapes}/scope_equal_area.parquet",
    log:
        "<logs>/{shapes}/prepare_shapes.log",
    conda:
        "../envs/module.yaml"
    params:
        step="shapes",
    script:
        "../scripts/prepare.py"


rule prepare_nuts3:
    input:
        shapes=rules.prepare_shapes.output.shapes,
        nuts3=rules.download_nuts3.output.geojson,
    output:
        regions="<resources>/automatic/{shapes}/nuts3.parquet",
    log:
        "<logs>/{shapes}/prepare_nuts3.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        step="nuts3",
        country_codes=internal["country_codes"],
    script:
        "../scripts/prepare.py"


checkpoint prepare_building_sources:
    input:
        regions=rules.prepare_nuts3.output.regions,
        microsoft_index=f"<resources>/automatic/microsoft/{config['buildings_microsoft']['release']}/dataset-links.csv",
    output:
        manifest="<resources>/automatic/{shapes}/buildings/plan.json",
        eubucco_nuts="<resources>/automatic/{shapes}/eubucco/NUTS-regions-2016.parquet",
        eubucco_stats="<resources>/automatic/{shapes}/eubucco/region-stats.parquet",
        empty_eubucco="<resources>/automatic/{shapes}/buildings/empty_eubucco.parquet",
        empty_microsoft="<resources>/automatic/{shapes}/buildings/empty_microsoft.parquet",
        empty_microsoft_totals="<resources>/automatic/{shapes}/buildings/empty_microsoft_totals.parquet",
        empty_microsoft_statistics="<resources>/automatic/{shapes}/buildings/empty_microsoft_tile_statistics.parquet",
    log:
        "<logs>/{shapes}/prepare_building_sources.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        step="building_sources",
        sources=internal["resources"]["automatic"],
        eubucco=config["buildings_eubucco"],
        eubucco_countries=internal["resources"]["eubucco_countries"],
        microsoft=config["buildings_microsoft"],
        proxies=config["data_proxies"],
    script:
        "../scripts/prepare.py"


rule download_eubucco:
    output:
        table=update(
            f"<resources>/automatic/eubucco/v{config['buildings_eubucco']['version']}/{config['buildings_eubucco']['source']}/downloads/{{region}}.parquet"
        ),
    log:
        f"<logs>/eubucco/v{config['buildings_eubucco']['version']}/{config['buildings_eubucco']['source']}/download_{{region}}.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        kind="eubucco",
        source=config["buildings_eubucco"]["source"],
        url=eubucco_download_url,
    script:
        "../scripts/download.py"


rule process_eubucco:
    input:
        plan=building_plan_input,
        regions=rules.prepare_nuts3.output.regions,
        downloads=eubucco_download_inputs,
    output:
        table=f"<resources>/automatic/{{shapes}}/eubucco/v{config['buildings_eubucco']['version']}/{config['buildings_eubucco']['source']}/buildings.parquet",
    log:
        f"<logs>/{{shapes}}/eubucco/v{config['buildings_eubucco']['version']}/{config['buildings_eubucco']['source']}/process.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    script:
        "../scripts/process_eubucco.py"


rule download_microsoft_index:
    output:
        table=update(
            f"<resources>/automatic/microsoft/{config['buildings_microsoft']['release']}/dataset-links.csv"
        ),
    log:
        f"<logs>/microsoft/{config['buildings_microsoft']['release']}/download_index.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        kind="microsoft_index",
        url=internal["resources"]["automatic"]["microsoft_index"].format(
            release=config["buildings_microsoft"]["release"]
        ),
    script:
        "../scripts/download.py"


rule download_microsoft:
    input:
        index=rules.download_microsoft_index.output.table,
    output:
        table=update(
            f"<resources>/automatic/microsoft/{config['buildings_microsoft']['release']}/downloads/{{quadkey}}-{{part}}.csv.gz"
        ),
    log:
        f"<logs>/microsoft/{config['buildings_microsoft']['release']}/download_{{quadkey}}_{{part}}.log",
    wildcard_constraints:
        quadkey="[0-3]{9}",
        part="[0-9]{5}",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        kind="microsoft",
    script:
        "../scripts/download.py"


rule process_microsoft:
    input:
        plan=building_plan_input,
        regions=rules.prepare_nuts3.output.regions,
        downloads=microsoft_download_inputs,
    output:
        table="<resources>/automatic/{shapes}/microsoft/buildings.parquet",
        totals="<resources>/automatic/{shapes}/microsoft/footprint_totals.parquet",
        statistics="<resources>/automatic/{shapes}/microsoft/tile_statistics.parquet",
    log:
        "<logs>/{shapes}/microsoft/process.log",
    conda:
        "../envs/module.yaml"
    resources:
        mem_mb=4096,
    script:
        "../scripts/process_microsoft.py"


rule extract_ghsl_population:
    input:
        rules.download_ghsl_population.output.archive,
    output:
        raster=f"<resources>/automatic/ghsl/pop_{config['population_ghsl']['epoch']}_100.tif",
    log:
        "<logs>/extract_ghsl_population.log",
    params:
        internal_paths=internal["resources"]["automatic"]["ghsl_stem"].format(
            epoch=config["population_ghsl"]["epoch"],
            resolution=config["population_ghsl"]["resolution"],
        )
        + "_V1_0.tif",
    wrapper:
        "v9.12.0/utils/libarchive/extract"
