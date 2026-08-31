"""Download regionalisation sources."""


rule download_residential_floor_area:
    output:
        raster="<resources>/automatic/hotmaps/gfa_res_curr_density.tif",
    log:
        "<logs>/download_residential_floor_area.log",
    conda:
        "../envs/module.yaml"
    params:
        url=internal["resources"]["automatic"]["floor_area_residential"],
    message:
        "Download the Hotmaps residential heated gross floor-area layer."
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.raster} "{params.url}" 2> {log}'


rule download_non_residential_floor_area:
    output:
        raster="<resources>/automatic/hotmaps/gfa_nonres_curr_density.tif",
    log:
        "<logs>/download_non_residential_floor_area.log",
    conda:
        "../envs/module.yaml"
    params:
        url=internal["resources"]["automatic"]["floor_area_non_residential"],
    message:
        "Download the Hotmaps non-residential heated gross floor-area layer."
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.raster} "{params.url}" 2> {log}'


rule download_residential_heat_density:
    output:
        raster="<resources>/automatic/hotmaps/heat_res_curr_density.tif",
    log:
        "<logs>/download_residential_heat_density.log",
    conda:
        "../envs/module.yaml"
    params:
        url=internal["resources"]["automatic"]["heat_density_residential"],
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.raster} "{params.url}" 2> {log}'


rule download_non_residential_heat_density:
    output:
        raster="<resources>/automatic/hotmaps/heat_nonres_curr_density.tif",
    log:
        "<logs>/download_non_residential_heat_density.log",
    conda:
        "../envs/module.yaml"
    params:
        url=internal["resources"]["automatic"]["heat_density_non_residential"],
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.raster} "{params.url}" 2> {log}'


rule download_eurostat_floor_area:
    output:
        table="<resources>/automatic/eurostat/cens_21dwbnr_r3.tsv.gz",
    log:
        "<logs>/download_eurostat_floor_area.log",
    conda:
        "../envs/module.yaml"
    params:
        url=internal["resources"]["automatic"]["eurostat_floor_area"],
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.table} "{params.url}" 2> {log}'


rule download_nuts3:
    output:
        geojson="<resources>/automatic/gisco/nuts3.geojson",
    log:
        "<logs>/download_nuts3.log",
    conda:
        "../envs/module.yaml"
    params:
        url=internal["resources"]["automatic"]["nuts3"],
    shell:
        'curl -fL --retry 3 --create-dirs -o {output.geojson} "{params.url}" 2> {log}'
