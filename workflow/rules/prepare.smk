"""Prepare land shapes and their overlapping NUTS-3 regions."""


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
    script:
        "../scripts/prepare_shapes.py"


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
        country_codes=internal["country_codes"],
    script:
        "../scripts/prepare_nuts3.py"
