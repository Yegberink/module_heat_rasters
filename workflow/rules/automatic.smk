"""Download regionalisation sources."""


use rule * from module_euro_building_heat as module_euro_building_heat_*


rule download_nuts3:
    output:
        geojson="<resources>/automatic/gisco/nuts3.geojson",
    log:
        "<logs>/download_nuts3.log",
    conda:
        "../envs/eubucco-download.yaml"
    params:
        url=internal["resources"]["automatic"]["nuts3"],
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.geojson} "{params.url}" 2> {log}'


rule download_eurostat_floor_area:
    output:
        table="<resources>/automatic/eurostat/cens_21dwbnr_r3.tsv.gz",
    log:
        "<logs>/download_eurostat_floor_area.log",
    conda:
        "../envs/download.yaml"
    params:
        url=internal["resources"]["automatic"]["eurostat_floor_area"],
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.table} "{params.url}" 2> {log}'


rule download_ghsl_population:
    output:
        archive=f"<resources>/automatic/ghsl/pop_{config['floor_area']['ghsl_epoch']}_100.zip",
    log:
        "<logs>/download_ghsl_population.log",
    conda:
        "../envs/download.yaml"
    params:
        url=internal["resources"]["automatic"]["ghsl_population"].format(
            stem=internal["resources"]["automatic"]["ghsl_stem"].format(
                epoch=config["floor_area"]["ghsl_epoch"],
                resolution=config["floor_area"]["ghsl_resolution"],
            )
        ),
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.archive} "{params.url}" 2> {log}'
